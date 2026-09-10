"""Look-alike verification (FR-007, AC-05).

Not every dark patch in a SAR image is oil.  Low wind, biogenic films, rain cells,
internal waves, upwelling and current shear all damp the short capillary waves that SAR
measures, and all of them look like a slick.  This package decides between them with an
explicit, inspectable rule set rather than a black box, because the verdict has to be
defensible to an investigator.

Three-class outcome (VERIFIED / UNCERTAIN / FALSE_POSITIVE) follows operational practice:
a binary verdict over-claims, and the uncertain class is what keeps the result usable as
evidence.
"""

from spilltrace.core.lookalike.engine import VerificationOutcome, verify_detection
from spilltrace.core.lookalike.features import SlickFeatures, extract_features

__all__ = [
    "SlickFeatures",
    "VerificationOutcome",
    "extract_features",
    "verify_detection",
]
