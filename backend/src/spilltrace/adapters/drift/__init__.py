"""Drift engines.

``analytical`` is always available and fully deterministic.  ``openoil`` wraps
OpenDrift's OpenOil model and is installed only when the image is built with
``INSTALL_DRIFT=true`` — see ``docs/DECISIONS.md`` AD-18 for why the fallback exists.
"""

from __future__ import annotations

from spilltrace.config import Settings, get_settings
from spilltrace.core.ports import DriftEngine
from spilltrace.logging import get_logger

log = get_logger(__name__)


def build_drift_engine(settings: Settings | None = None) -> DriftEngine:
    settings = settings or get_settings()
    if settings.drift_engine == "openoil":
        try:
            from spilltrace.adapters.drift.openoil import OpenOilEngine

            return OpenOilEngine()
        except ImportError as exc:
            # Degrade loudly: the run will be tagged engine='analytical' and the UI and
            # report will say a physics model was not used (AD-7).
            log.warning(
                "opendrift_unavailable_using_analytical_engine",
                error=str(exc),
                remedy="rebuild the image with INSTALL_DRIFT=true",
            )
    from spilltrace.adapters.drift.analytical import AnalyticalDriftEngine

    return AnalyticalDriftEngine()


__all__ = ["build_drift_engine"]
