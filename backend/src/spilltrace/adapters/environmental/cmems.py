"""Copernicus Marine (CMEMS) wind and current provider (FR-008, docs/DECISIONS.md AD-17).

Uses the ``copernicusmarine`` toolbox v2 (``open_dataset``, not ``subset`` — no file
staging, a lazy ARCO-Zarr view is enough).  Credentials are read automatically from
``COPERNICUSMARINE_SERVICE_USERNAME`` / ``_PASSWORD``.

Datasets (AD-17):

* currents — ``cmems_mod_glo_phy_anfc_merged-uv_PT1H-i`` (hourly merged surface currents:
  circulation + tides + waves, single level z ~ -0.494 m, variables ``uo``/``vo``);
* wind — ``cmems_obs-wind_glo_phy_nrt_l4_0.125deg_PT1H`` (NRT L4 scatterometer+model,
  ``eastward_wind`` / ``northward_wind``).

**Known coverage gap (recorded, not hidden):** the NRT wind product starts June 2024 and
the reanalysis lags real time by months.  A request outside the NRT window raises
``ProviderUnavailableError`` so the caller can fall back rather than silently getting a
truncated field.

The CMEMS licence requires attribution; ``ATTRIBUTION`` is surfaced into the run manifest
and the evidence report by the drift handler.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import numpy as np

from spilltrace.config import Settings, get_settings
from spilltrace.core.enums import DataProvenance
from spilltrace.core.errors import ProviderAuthError, ProviderUnavailableError
from spilltrace.core.ports import EnvironmentalBundle, EnvironmentalField
from spilltrace.logging import get_logger

log = get_logger(__name__)

CURRENTS_DATASET = "cmems_mod_glo_phy_anfc_merged-uv_PT1H-i"
WIND_DATASET = "cmems_obs-wind_glo_phy_nrt_l4_0.125deg_PT1H"

#: The NRT wind L4 product's start (AD-17).  Requests earlier than this cannot be served.
WIND_NRT_START = datetime(2024, 6, 1, tzinfo=UTC)

ATTRIBUTION = (
    "Generated using E.U. Copernicus Marine Service Information; "
    "https://doi.org/10.48670/moi-00016 (currents), "
    "https://doi.org/10.48670/mds-00329 (wind)."
)


class CopernicusMarineProvider:
    """Implements :class:`spilltrace.core.ports.EnvironmentalProvider`."""

    name = "cmems"

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        try:
            import copernicusmarine  # noqa: F401
        except ImportError as exc:  # pragma: no cover - guarded by the builder
            raise ImportError(
                "copernicusmarine is not installed. Rebuild the backend image with "
                "INSTALL_PROVIDERS=true."
            ) from exc

    async def fetch(
        self, *, bbox: tuple[float, float, float, float], start: datetime, end: datetime
    ) -> EnvironmentalBundle:
        if end < WIND_NRT_START:
            raise ProviderUnavailableError(
                "The Copernicus Marine NRT wind product only covers June 2024 onward. "
                "This time window predates it; ERA5 (CDS API) is the historical fallback.",
                provider="cmems",
            )
        # copernicusmarine is synchronous and does network + xarray work; keep it off
        # the event loop.
        return await asyncio.to_thread(self._fetch_sync, bbox, start, end)

    def _fetch_sync(
        self, bbox: tuple[float, float, float, float], start: datetime, end: datetime
    ) -> EnvironmentalBundle:
        import copernicusmarine

        min_lon, min_lat, max_lon, max_lat = bbox
        common = {
            "minimum_longitude": min_lon,
            "maximum_longitude": max_lon,
            "minimum_latitude": min_lat,
            "maximum_latitude": max_lat,
            "start_datetime": start,
            "end_datetime": end,
            "username": self._settings.cmems_username,
            "password": self._settings.cmems_password,
        }

        try:
            currents = copernicusmarine.open_dataset(dataset_id=CURRENTS_DATASET, **common)
            wind = copernicusmarine.open_dataset(dataset_id=WIND_DATASET, **common)
        except Exception as exc:  # normalise to a domain error
            message = str(exc).lower()
            if "credential" in message or "auth" in message or "401" in message:
                raise ProviderAuthError(
                    "Copernicus Marine rejected the credentials.", provider="cmems"
                ) from exc
            raise ProviderUnavailableError(
                f"Copernicus Marine request failed: {type(exc).__name__}", provider="cmems"
            ) from exc

        cu, cv, c_axes = self._extract(currents, ("uo", "utotal"), ("vo", "vtotal"))
        wu, wv, w_axes = self._extract(wind, ("eastward_wind", "u"), ("northward_wind", "v"))

        def field(
            name: str, values: np.ndarray, axes: dict[str, Any], ds_id: str
        ) -> EnvironmentalField:
            return EnvironmentalField(
                variable=name,
                units="m s-1",
                times=axes["times"],
                lats=axes["lats"],
                lons=axes["lons"],
                values=values,
                source="cmems",
                dataset_id=ds_id,
                data_provenance=DataProvenance.REAL,
            )

        currents.close()
        wind.close()
        log.info(
            "cmems_fetch_complete",
            currents=CURRENTS_DATASET,
            wind=WIND_DATASET,
            wind_shape=list(wu.shape),
        )
        return EnvironmentalBundle(
            wind_u=field("eastward_wind", wu, w_axes, WIND_DATASET),
            wind_v=field("northward_wind", wv, w_axes, WIND_DATASET),
            current_u=field("eastward_current", cu, c_axes, CURRENTS_DATASET),
            current_v=field("northward_current", cv, c_axes, CURRENTS_DATASET),
            source="cmems",
            dataset_ids={"wind": WIND_DATASET, "currents": CURRENTS_DATASET},
            data_provenance=DataProvenance.REAL,
        )

    @staticmethod
    def _extract(
        ds: Any, u_names: tuple[str, ...], v_names: tuple[str, ...]
    ) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
        """Pull the first matching u/v variable, squeezing any singleton depth axis."""
        import pandas as pd

        def pick(names: tuple[str, ...]) -> Any:
            for n in names:
                if n in ds.variables:
                    return ds[n]
            raise ProviderUnavailableError(
                f"None of {names} present in the Copernicus dataset (has {list(ds.data_vars)}).",
                provider="cmems",
            )

        u_da, v_da = pick(u_names), pick(v_names)
        # A singleton depth/elevation axis is dropped by .squeeze() below; nothing to do
        # here beyond picking the variables.

        lat_name = "latitude" if "latitude" in u_da.coords else "lat"
        lon_name = "longitude" if "longitude" in u_da.coords else "lon"
        u = np.asarray(u_da.squeeze().values, dtype=np.float32)
        v = np.asarray(v_da.squeeze().values, dtype=np.float32)
        if u.ndim == 2:  # single timestep — add the time axis back
            u = u[np.newaxis, ...]
            v = v[np.newaxis, ...]

        times = tuple(
            t.to_pydatetime().replace(tzinfo=UTC)
            for t in pd.to_datetime(np.atleast_1d(u_da["time"].values))
        )
        axes = {
            "times": times,
            "lats": tuple(float(x) for x in np.atleast_1d(u_da[lat_name].values)),
            "lons": tuple(float(x) for x in np.atleast_1d(u_da[lon_name].values)),
        }
        return u, v, axes


__all__ = [
    "ATTRIBUTION",
    "CURRENTS_DATASET",
    "WIND_DATASET",
    "WIND_NRT_START",
    "CopernicusMarineProvider",
]
