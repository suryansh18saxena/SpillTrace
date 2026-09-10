"""Persist an environmental bundle to object storage.

NPZ rather than NetCDF for the synthetic path: it is dependency-free, exactly
round-trips the arrays, and keeps the demo runnable without the optional ``netcdf``
extra.  The real CMEMS adapter stores the provider's NetCDF unchanged, because for a
real run the original file *is* the evidence.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from typing import Any

import numpy as np

from spilltrace.core.enums import DataProvenance
from spilltrace.core.ports import EnvironmentalBundle, EnvironmentalField

FORMAT_VERSION = 1


def bundle_to_bytes(bundle: EnvironmentalBundle) -> bytes:
    buffer = io.BytesIO()
    payload: dict[str, Any] = {
        "format_version": np.asarray(FORMAT_VERSION),
        "source": np.asarray(bundle.source),
        "data_provenance": np.asarray(str(bundle.data_provenance)),
        "times": np.asarray([t.astimezone(UTC).isoformat() for t in bundle.wind_u.times]),
        "lats": np.asarray(bundle.wind_u.lats, dtype=np.float64),
        "lons": np.asarray(bundle.wind_u.lons, dtype=np.float64),
    }
    for name, field_obj in (
        ("wind_u", bundle.wind_u),
        ("wind_v", bundle.wind_v),
        ("current_u", bundle.current_u),
        ("current_v", bundle.current_v),
    ):
        payload[name] = np.asarray(field_obj.values, dtype=np.float32)
        payload[f"{name}__variable"] = np.asarray(field_obj.variable)
        payload[f"{name}__units"] = np.asarray(field_obj.units)
        payload[f"{name}__dataset_id"] = np.asarray(field_obj.dataset_id or "")
    np.savez_compressed(buffer, **payload)
    return buffer.getvalue()


def bundle_from_bytes(data: bytes) -> EnvironmentalBundle:
    with np.load(io.BytesIO(data), allow_pickle=False) as archive:
        times = tuple(datetime.fromisoformat(str(t)) for t in archive["times"])
        lats = tuple(float(v) for v in archive["lats"])
        lons = tuple(float(v) for v in archive["lons"])
        source = str(archive["source"])
        provenance = DataProvenance(str(archive["data_provenance"]))

        def field(name: str) -> EnvironmentalField:
            dataset_id = str(archive[f"{name}__dataset_id"])
            return EnvironmentalField(
                variable=str(archive[f"{name}__variable"]),
                units=str(archive[f"{name}__units"]),
                times=times,
                lats=lats,
                lons=lons,
                values=archive[name],
                source=source,
                dataset_id=dataset_id or None,
                data_provenance=provenance,
            )

        return EnvironmentalBundle(
            wind_u=field("wind_u"),
            wind_v=field("wind_v"),
            current_u=field("current_u"),
            current_v=field("current_v"),
            source=source,
            data_provenance=provenance,
        )


__all__ = ["FORMAT_VERSION", "bundle_from_bytes", "bundle_to_bytes"]
