"""Mandated product language (PRD Part K, CON-001…CON-003, CON-007, CON-008, AC-13).

The PRD is explicit that SPILLTRACE produces investigative evidence, not legal proof.
Centralising the wording here means the API, the UI and the evidence report cannot
drift apart, and lets ``tests/unit/test_disclaimers.py`` assert that every
attribution-bearing response actually carries it.
"""

from __future__ import annotations

import re
from typing import Final

#: Shown on every attribution, ranking view and report.
ATTRIBUTION_DISCLAIMER: Final[str] = (
    "Attribution is investigative/probabilistic evidence and is not automatic legal proof."
)

#: Shown wherever a final score is displayed.
SCORE_DISCLAIMER: Final[str] = (
    "This score combines six weighted evidence factors using prototype engineering "
    "weights. It is not a calibrated legal probability and must not be read as one."
)

#: Shown on the origin probability region.
ORIGIN_REGION_DISCLAIMER: Final[str] = (
    "The origin region is a probability region derived from reverse drift simulation. "
    "It indicates where a discharge was more likely to have occurred; it is not an "
    "exact discharge coordinate."
)

#: Shown wherever an AIS reporting gap is displayed.
AIS_GAP_DISCLAIMER: Final[str] = (
    "A gap in AIS reporting is not evidence of wrongdoing. Gaps are commonly caused by "
    "satellite revisit intervals, terrestrial receiver coverage, signal interference in "
    "busy waters, and equipment faults."
)

#: Shown wherever candidate vessels are listed.
PROXIMITY_DISCLAIMER: Final[str] = (
    "Proximity to the origin region does not by itself indicate responsibility. "
    "Candidates are ranked to prioritise further investigation, not to assign blame."
)

#: Shown wherever AIS coverage is summarised.
AIS_COVERAGE_DISCLAIMER: Final[str] = (
    "AIS coverage is not complete. Vessels may be absent from this dataset because they "
    "were outside receiver coverage, because their transmissions collided with others, "
    "or because they do not carry AIS. Absence of a vessel is not evidence of absence."
)

#: Shown on any detection produced by a model.
DETECTION_DISCLAIMER: Final[str] = (
    "Automated detection identifies oil-like surface features in SAR imagery. Dark "
    "features may also be produced by low wind, biogenic films, rain cells and other "
    "natural phenomena; see the look-alike verification result."
)

#: Shown on any artifact whose provenance is not REAL.
SYNTHETIC_DATA_NOTICE: Final[str] = (
    "SYNTHETIC DEMONSTRATION DATA — generated deterministically by SPILLTRACE for "
    "development and demonstration. It does not represent any real vessel, spill, "
    "satellite observation or environmental measurement."
)

#: Sections that must appear in every evidence report (AC-12).
REPORT_LIMITATIONS: Final[tuple[str, ...]] = (
    ATTRIBUTION_DISCLAIMER,
    SCORE_DISCLAIMER,
    ORIGIN_REGION_DISCLAIMER,
    AIS_GAP_DISCLAIMER,
    PROXIMITY_DISCLAIMER,
    AIS_COVERAGE_DISCLAIMER,
    DETECTION_DISCLAIMER,
)

#: Every mandated text, used to exclude our own safeguards from the language scan.
_ALL_DISCLAIMERS: Final[tuple[str, ...]] = (
    ATTRIBUTION_DISCLAIMER,
    SCORE_DISCLAIMER,
    ORIGIN_REGION_DISCLAIMER,
    AIS_GAP_DISCLAIMER,
    PROXIMITY_DISCLAIMER,
    AIS_COVERAGE_DISCLAIMER,
    DETECTION_DISCLAIMER,
    SYNTHETIC_DATA_NOTICE,
)

#: Language that must never appear in generated output.  Asserted by tests.
FORBIDDEN_PHRASES: Final[tuple[str, ...]] = (
    "responsible vessel",
    "guilty",
    "proven",
    "definitely caused",
    "legal probability",
    "confirmed polluter",
    "the polluter is",
)


def contains_forbidden_language(text: str, *, ignore_disclaimers: bool = True) -> list[str]:
    """Return any forbidden phrases found in ``text`` (case-insensitive).

    Two subtleties, both learned from false positives:

    * **Word boundaries.** A plain substring search flags "proven" inside "provenance",
      which appears on every artifact in the system. Matching is therefore anchored to
      word boundaries.
    * **The disclaimers quote what they forbid.** ``SCORE_DISCLAIMER`` says a score "is
      not a calibrated legal probability", which contains the forbidden phrase in order
      to deny it. Scanning a rendered document would flag our own safeguard, so the
      mandated texts are removed before scanning. Pass ``ignore_disclaimers=False`` to
      scan the raw text.
    """
    haystack = text
    if ignore_disclaimers:
        for mandated in _ALL_DISCLAIMERS:
            haystack = haystack.replace(mandated, " ")
            haystack = haystack.replace(mandated.lower(), " ")
    lowered = haystack.lower()
    return [
        phrase
        for phrase in FORBIDDEN_PHRASES
        if re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", lowered)
    ]


__all__ = [
    "AIS_COVERAGE_DISCLAIMER",
    "AIS_GAP_DISCLAIMER",
    "ATTRIBUTION_DISCLAIMER",
    "DETECTION_DISCLAIMER",
    "FORBIDDEN_PHRASES",
    "ORIGIN_REGION_DISCLAIMER",
    "PROXIMITY_DISCLAIMER",
    "REPORT_LIMITATIONS",
    "SCORE_DISCLAIMER",
    "SYNTHETIC_DATA_NOTICE",
    "contains_forbidden_language",
]
