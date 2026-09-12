"""Oil-probability raster tiles (API.md §7, P23-012).

``GET /api/v1/cases/{case_id}/probability/{z}/{x}/{y}.png`` renders the latest
``PROBABILITY_RASTER`` artifact of a case as Web-Mercator XYZ tiles, so the map can show
*what the model saw* underneath the polygon it produced.

Design points:

- **Colour is the confidence ramp**, not a heat map: warm grey → amber → gold, exactly
  the ordinal ramp every score in the product uses, and never red (CON-001/003).
  Probability below 0.05 is fully transparent so the scene is not painted over.
- **Outside the raster is a transparent tile, not a 404.** A 404 on a legitimately empty
  tile makes MapLibre log errors for every tile of the world.
- **The raster is read once per case** and kept in a small in-process cache keyed by the
  artifact checksum, bounded in count (the working raster is at most 4096² float32).
- Access control is the same as every other case endpoint: the case must be visible to
  the caller.
"""

from __future__ import annotations

import math
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

import numpy as np
from fastapi import APIRouter, Response
from rasterio.enums import Resampling
from rasterio.transform import from_bounds
from rasterio.warp import reproject
from sqlalchemy import select

from spilltrace.adapters.storage import build_object_store
from spilltrace.api.auth import CurrentUser
from spilltrace.api.deps import SessionDep, SettingsDep
from spilltrace.core.enums import ArtifactType
from spilltrace.core.raster import array_to_png, read_geotiff
from spilltrace.db.models import EvidenceArtifact
from spilltrace.db.repositories.cases import CaseRepository
from spilltrace.logging import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/api/v1/cases/{case_id}/probability", tags=["layers"])

TILE_SIZE = 256
MAX_ZOOM = 18
#: Rasters kept in memory across requests (LRU).  Each is ≤ 64 MB.
CACHE_ENTRIES = 4
WEB_MERCATOR = "EPSG:3857"
#: Half the Web-Mercator world width, in metres.
HALF_WORLD = 20037508.342789244

_CACHE_HEADERS = {"Cache-Control": "private, max-age=3600"}


@dataclass(frozen=True, slots=True)
class ProbabilityRaster:
    array: np.ndarray  # (H, W) float32 in [0, 1], 0 where no data
    bounds: tuple[float, float, float, float]  # WGS84 min_x, min_y, max_x, max_y
    crs: str
    checksum: str


class _RasterCache:
    def __init__(self, entries: int) -> None:
        self._entries = entries
        self._items: OrderedDict[str, ProbabilityRaster] = OrderedDict()

    def get(self, key: str) -> ProbabilityRaster | None:
        raster = self._items.get(key)
        if raster is not None:
            self._items.move_to_end(key)
        return raster

    def put(self, key: str, raster: ProbabilityRaster) -> None:
        self._items[key] = raster
        self._items.move_to_end(key)
        while len(self._items) > self._entries:
            self._items.popitem(last=False)


_cache = _RasterCache(CACHE_ENTRIES)
_transparent_tile: bytes | None = None


def transparent_tile() -> bytes:
    global _transparent_tile
    if _transparent_tile is None:
        _transparent_tile = array_to_png(
            np.zeros((TILE_SIZE, TILE_SIZE), dtype=np.float32), colormap="confidence"
        )
    return _transparent_tile


def tile_bounds_mercator(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """XYZ tile → EPSG:3857 bounds ``(min_x, min_y, max_x, max_y)``."""
    n = 2**z
    size = 2 * HALF_WORLD / n
    min_x = -HALF_WORLD + x * size
    max_y = HALF_WORLD - y * size
    return (min_x, max_y - size, min_x + size, max_y)


def tile_bounds_wgs84(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """XYZ tile → lon/lat bounds, for the cheap intersection test."""
    n = 2**z
    lon_min = x / n * 360.0 - 180.0
    lon_max = (x + 1) / n * 360.0 - 180.0
    lat_max = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    lat_min = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return (lon_min, lat_min, lon_max, lat_max)


def _intersects(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return not (a[2] <= b[0] or a[0] >= b[2] or a[3] <= b[1] or a[1] >= b[3])


def render_tile(raster: ProbabilityRaster, z: int, x: int, y: int) -> bytes:
    """Reproject the raster window under one tile and colourise it."""
    if not _intersects(raster.bounds, tile_bounds_wgs84(z, x, y)):
        return transparent_tile()
    destination = np.zeros((TILE_SIZE, TILE_SIZE), dtype=np.float32)
    src_transform = from_bounds(*raster.bounds, raster.array.shape[1], raster.array.shape[0])
    dst_transform = from_bounds(*tile_bounds_mercator(z, x, y), TILE_SIZE, TILE_SIZE)
    reproject(
        source=raster.array,
        destination=destination,
        src_transform=src_transform,
        src_crs=raster.crs,
        src_nodata=0.0,
        dst_transform=dst_transform,
        dst_crs=WEB_MERCATOR,
        dst_nodata=0.0,
        resampling=Resampling.bilinear,
    )
    if not np.any(destination > 0.0):
        return transparent_tile()
    return array_to_png(destination, colormap="confidence")


async def _latest_raster(
    session: Any, settings: Any, case_id: uuid.UUID
) -> ProbabilityRaster | None:
    artifact = (
        await session.execute(
            select(EvidenceArtifact)
            .where(
                EvidenceArtifact.case_id == case_id,
                EvidenceArtifact.artifact_type == ArtifactType.PROBABILITY_RASTER.value,
            )
            .order_by(EvidenceArtifact.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if artifact is None or not artifact.storage_uri:
        return None

    cached = _cache.get(artifact.checksum_sha256)
    if cached is not None:
        return cached

    store = build_object_store(settings)
    payload = await store.get_bytes(artifact.storage_uri.split("/", 3)[-1])
    array, meta = read_geotiff(payload)
    band = np.nan_to_num(array[0].astype(np.float32), nan=0.0)
    raster = ProbabilityRaster(
        array=np.clip(band, 0.0, 1.0),
        bounds=tuple(float(v) for v in meta["bounds"]),  # type: ignore[arg-type]
        crs=str(meta["crs"] or "EPSG:4326"),
        checksum=artifact.checksum_sha256,
    )
    _cache.put(artifact.checksum_sha256, raster)
    log.info(
        "probability_raster_loaded",
        case_id=str(case_id),
        shape=list(raster.array.shape),
        checksum=artifact.checksum_sha256[:12],
    )
    return raster


@router.get(
    "/{z}/{x}/{y}.png",
    summary="Oil-probability raster as a Web-Mercator XYZ tile",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
async def probability_tile(
    case_id: uuid.UUID,
    z: int,
    x: int,
    y: int,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> Response:
    await CaseRepository(session).get_for_user(case_id, user)
    if not (0 <= z <= MAX_ZOOM) or not (0 <= x < 2**z) or not (0 <= y < 2**z):
        return Response(content=transparent_tile(), media_type="image/png", headers=_CACHE_HEADERS)

    raster = await _latest_raster(session, settings, case_id)
    if raster is None:
        # No detection stage has run yet: an empty tile, cached briefly so the map
        # re-checks once the pipeline has produced something.
        return Response(
            content=transparent_tile(),
            media_type="image/png",
            headers={"Cache-Control": "private, max-age=30"},
        )
    etag = f'"{raster.checksum[:16]}-{z}-{x}-{y}"'
    return Response(
        content=render_tile(raster, z, x, y),
        media_type="image/png",
        headers={**_CACHE_HEADERS, "ETag": etag},
    )


__all__ = ["render_tile", "router", "tile_bounds_mercator", "tile_bounds_wgs84"]
