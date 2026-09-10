"""Optional classifier hook.

The PRD allows an optional learned classifier alongside the rule engine.  It is off by
default: a transparent rule set is defensible to an investigator, and a model with no
measured performance on our data would add opacity without adding evidence.  When a
model does exist and has been evaluated, it plugs in here and contributes a bounded
share of the evidence score.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from spilltrace.core.lookalike.features import SlickFeatures


@runtime_checkable
class LookalikeClassifier(Protocol):
    name: str

    def predict(self, features: SlickFeatures) -> float:
        """Probability in [0, 1] that the feature is oil rather than a look-alike."""
        ...


def build_classifier(name: str | None = None) -> LookalikeClassifier | None:
    """Resolve a configured classifier, or ``None`` when none is enabled."""
    if not name or name == "none":
        return None
    raise NotImplementedError(
        f"No look-alike classifier named '{name}' is registered. Train and evaluate one, "
        "record its measured metrics in model_versions, then register it here."
    )


__all__ = ["LookalikeClassifier", "build_classifier"]
