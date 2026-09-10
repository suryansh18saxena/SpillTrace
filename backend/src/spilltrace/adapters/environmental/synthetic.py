"""Deterministic environmental provider.

Implements the same port as the Copernicus Marine adapter, so nothing downstream can
tell which one produced a field except by reading ``data_provenance`` — which is exactly
the point (AD-5).
"""

from __future__ import annotations

from datetime import datetime

from spilltrace.core.ports import EnvironmentalBundle
from spilltrace.demo.environment import synthetic_environment


class SyntheticEnvironmentProvider:
    name = "synthetic"

    def __init__(
        self,
        *,
        wind_speed_ms: float = 5.4,
        wind_direction_deg: float = 232.0,
        current_speed_ms: float = 0.31,
        current_direction_deg: float = 104.0,
        seed: int = 42,
    ) -> None:
        self.wind_speed_ms = wind_speed_ms
        self.wind_direction_deg = wind_direction_deg
        self.current_speed_ms = current_speed_ms
        self.current_direction_deg = current_direction_deg
        self.seed = seed

    async def fetch(
        self, *, bbox: tuple[float, float, float, float], start: datetime, end: datetime
    ) -> EnvironmentalBundle:
        return synthetic_environment(
            bbox=bbox,
            start=start,
            end=end,
            wind_speed_ms=self.wind_speed_ms,
            wind_direction_deg=self.wind_direction_deg,
            current_speed_ms=self.current_speed_ms,
            current_direction_deg=self.current_direction_deg,
            seed=self.seed,
        )


__all__ = ["SyntheticEnvironmentProvider"]
