"""Satellite catalogue adapters.

``cdse`` talks to the Copernicus Data Space Ecosystem; ``fixture`` answers from
arithmetic.  The choice is a configuration one, and it is **always logged**, because an
analyst reading a case must be able to tell whether a scene was observed or generated.

Selecting ``cdse`` without credentials does not fail the process and does not silently
pretend to be real: the fixture is returned and the reason is logged, and every artifact
downstream carries ``data_provenance=SYNTHETIC`` as a result.
"""

from __future__ import annotations

from spilltrace.config import Settings, get_settings
from spilltrace.core.ports import SatelliteCatalogue
from spilltrace.logging import get_logger

log = get_logger(__name__)


def build_satellite_catalogue(settings: Settings | None = None) -> SatelliteCatalogue:
    settings = settings or get_settings()
    if settings.satellite_provider == "cdse":
        if settings.cdse_username and settings.cdse_password:
            from spilltrace.adapters.satellite.cdse import CDSECatalogue
            from spilltrace.adapters.satellite.cdse_auth import CDSECredentials

            log.info(
                "satellite_catalogue_selected",
                provider="cdse",
                mode="REAL",
                reason="CDSE credentials are configured",
            )
            return CDSECatalogue(
                CDSECredentials(
                    username=settings.cdse_username,
                    password=settings.cdse_password,
                    client_id=settings.cdse_client_id,
                )
            )
        log.warning(
            "satellite_catalogue_degraded",
            provider="fixture",
            mode="SYNTHETIC",
            requested="cdse",
            reason="CDSE_USERNAME/CDSE_PASSWORD are not set",
            remedy="set both in .env, then restart the worker",
        )
    else:
        log.info(
            "satellite_catalogue_selected",
            provider="fixture",
            mode="SYNTHETIC",
            reason="SPILLTRACE_SATELLITE_PROVIDER=fixture",
        )

    from spilltrace.adapters.satellite.fixture import FixtureCatalogue

    return FixtureCatalogue()


__all__ = ["build_satellite_catalogue"]
