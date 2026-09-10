"""Wind and ocean-current providers."""

from __future__ import annotations

from spilltrace.config import Settings, get_settings
from spilltrace.core.ports import EnvironmentalProvider


def build_environmental_provider(settings: Settings | None = None) -> EnvironmentalProvider:
    settings = settings or get_settings()
    if settings.environment_provider == "cmems":
        from spilltrace.adapters.environmental.cmems import CopernicusMarineProvider

        return CopernicusMarineProvider(settings)
    from spilltrace.adapters.environmental.synthetic import SyntheticEnvironmentProvider

    return SyntheticEnvironmentProvider()


__all__ = ["build_environmental_provider"]
