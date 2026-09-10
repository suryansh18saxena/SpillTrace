"""Copernicus Data Space Ecosystem catalogue and download adapter (AD-07, AD-08).

Search uses **OData, not STAC**.  Both work, but STAC's ``product:type`` is
platform-dependent — Sentinel-1C scenes carry ``IW_GRDH_1S_C`` while Sentinel-1A carries
``IW_GRDH_1S`` — so a STAC filter on ``product:type`` silently drops every S1C scene.
OData uses ``IW_GRDH_1S`` for both and exposes the full attribute set via
``$expand=Attributes``.

Download fetches **one Cloud-Optimised GeoTIFF per polarisation from the zipper node
endpoint** rather than the whole SAFE archive: ~1.0 GB against ~1.7 GB on a measured
scene, and a COG can be window-read by rasterio without pulling the whole file.

Everything the live APIs actually do that is easy to get wrong is encoded here:

* the search polygon must be closed;
* ``polarisationChannels`` is the ampersand-joined string ``"VV&VH"``, not a list;
* ``relativeOrbitNumber`` is an ``OData.CSC.IntegerAttribute``;
* ``orbitDirection`` is upper-case in OData (lower-case in STAC);
* ``HEAD`` on the download endpoint answers **405**, so the size probe is a ranged GET;
* redirects must be followed with the ``Authorization`` header retained;
* the free tier allows **4 concurrent connections**, which is the download semaphore.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry

from spilltrace.adapters.satellite.bundle import (
    SceneBand,
    SceneBundle,
    bundle_stored_object,
    sha256_file,
    write_bundle,
)
from spilltrace.adapters.satellite.cdse_auth import CDSECredentials, CDSETokenManager
from spilltrace.core.enums import DataProvenance
from spilltrace.core.errors import ProviderError, ProviderUnavailableError
from spilltrace.core.geometry import parse_geojson_geometry
from spilltrace.core.ports import ProgressCallback, SceneRecord, StoredObject
from spilltrace.core.time import ensure_utc
from spilltrace.logging import get_logger

log = get_logger(__name__)

PROVIDER = "cdse"

CATALOGUE_URL = "https://catalogue.dataspace.copernicus.eu/odata/v1"
#: The zipper host is what serves ``$value`` for a product or one of its nodes.
ZIPPER_URL = "https://zipper.dataspace.copernicus.eu/odata/v1"

DEFAULT_COLLECTION = "SENTINEL-1"
DEFAULT_PRODUCT_TYPE = "IW_GRDH_1S"
COG_SUFFIX = "-COG"

#: Free tier: 4 concurrent connections, 2 000 requests/minute, 12 TB per 30 days.
MAX_CONCURRENT_DOWNLOADS = 4
#: The search polygon is simplified below this many vertices; CDSE rejects long filters.
MAX_FILTER_VERTICES = 40
DOWNLOAD_CHUNK_BYTES = 4 * 1024 * 1024
MAX_TRANSFER_ATTEMPTS = 4
MAX_REDIRECTS = 5

_TIMEOUT = httpx.Timeout(connect=15.0, read=120.0, write=120.0, pool=15.0)
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.\-]+$")


@dataclass(frozen=True, slots=True)
class MeasurementNode:
    """One measurement file inside a product, as the node listing describes it."""

    name: str
    size_bytes: int

    @property
    def polarization(self) -> str | None:
        """Sentinel-1 measurement files encode polarisation as ``-vv-`` / ``-vh-``."""
        lowered = self.name.lower()
        for channel in ("vv", "vh", "hh", "hv"):
            if f"-{channel}-" in lowered:
                return channel.upper()
        return None

    @property
    def is_cog(self) -> bool:
        return self.name.lower().endswith("-cog.tiff")


class CDSECatalogue:
    """Sentinel-1 catalogue search and per-band download against CDSE."""

    name = "cdse"

    def __init__(
        self,
        credentials: CDSECredentials,
        *,
        client: httpx.AsyncClient | None = None,
        token_manager: CDSETokenManager | None = None,
        catalogue_url: str = CATALOGUE_URL,
        download_url: str = ZIPPER_URL,
        max_concurrency: int = MAX_CONCURRENT_DOWNLOADS,
    ) -> None:
        self._client = client
        self._owns_client = client is None
        self._catalogue_url = catalogue_url.rstrip("/")
        self._download_url = download_url.rstrip("/")
        self._tokens = token_manager or CDSETokenManager(credentials, client=client)
        # The cap is a provider quota, not a tuning knob: exceeding it earns a 429.
        self._semaphore = asyncio.Semaphore(max(1, min(max_concurrency, MAX_CONCURRENT_DOWNLOADS)))

    # ------------------------------------------------------------------ lifecycle
    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            # Redirects are followed by hand so the Authorization header survives them.
            self._client = httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False)
        return self._client

    async def aclose(self) -> None:
        await self._tokens.aclose()
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def max_concurrency(self) -> int:
        """The download semaphore's ceiling — a provider quota, not a tuning knob."""
        return self._semaphore._value if not self._semaphore.locked() else 0

    def describe(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "catalogue": self._catalogue_url,
            "download": self._download_url,
            "protocol": "OData",
            "max_concurrent_downloads": MAX_CONCURRENT_DOWNLOADS,
        }

    # ------------------------------------------------------------------ search
    async def search(
        self,
        *,
        aoi_geojson: dict[str, Any],
        start: datetime,
        end: datetime,
        product_type: str = DEFAULT_PRODUCT_TYPE,
        limit: int = 50,
    ) -> list[SceneRecord]:
        wkt = aoi_to_wkt_polygon(aoi_geojson)
        odata_filter = build_odata_filter(
            wkt=wkt,
            start=ensure_utc(start, field="start"),
            end=ensure_utc(end, field="end"),
            product_type=product_type,
        )
        params = {
            "$filter": odata_filter,
            "$expand": "Attributes",
            "$orderby": "ContentDate/Start asc",
            "$top": str(max(1, min(limit, 1000))),
        }
        payload = await self._get_json(f"{self._catalogue_url}/Products", params=params)
        products = payload.get("value")
        if not isinstance(products, list):
            raise ProviderError(
                "The Copernicus catalogue returned no 'value' array.", provider=PROVIDER
            )
        records = [parse_product(product) for product in products]
        log.info(
            "cdse_search_complete",
            results=len(records),
            product_type=product_type,
            window_start=start.isoformat(),
            window_end=end.isoformat(),
        )
        return records

    # ------------------------------------------------------------------ download
    async def download(
        self,
        record: SceneRecord,
        *,
        destination: str,
        progress: ProgressCallback | None = None,
        polarizations: tuple[str, ...] = (),
    ) -> StoredObject:
        """Fetch one measurement file per polarisation into ``destination``.

        Returns a :class:`StoredObject` describing the destination directory; the band
        files it contains are enumerated in ``bundle.json`` beside them.
        """
        target = Path(destination)
        await asyncio.to_thread(target.mkdir, parents=True, exist_ok=True)

        wanted = tuple(p.upper() for p in (polarizations or record.polarizations or ("VV", "VH")))
        product_uuid, safe_name, notes = await self._resolve_download_product(record)
        nodes = await self._measurement_nodes(product_uuid, safe_name)
        selected = select_band_nodes(nodes, wanted)
        if not selected:
            raise ProviderError(
                f"Product {record.product_id} exposes no measurement file for {', '.join(wanted)}.",
                provider=PROVIDER,
                available=[node.name for node in nodes],
            )
        missing = [channel for channel in wanted if channel not in selected]
        for channel in missing:
            notes.append(
                f"{channel} is not present in this product; it was not downloaded. "
                "Downstream preprocessing records the substitution it made."
            )

        total_expected = sum(node.size_bytes for node in selected.values()) or 1
        transferred = dict.fromkeys(selected, 0)
        lock = asyncio.Lock()

        async def report(channel: str, done: int) -> None:
            if progress is None:
                return
            async with lock:
                transferred[channel] = done
                fraction = min(0.99, sum(transferred.values()) / total_expected)
            await progress(fraction=fraction, message=f"downloading {channel}")

        async def fetch(channel: str, node: MeasurementNode) -> SceneBand:
            async with self._semaphore:
                url = self._node_value_url(product_uuid, safe_name, node.name)
                path = target / node.name
                size = await self._download_to(url, path, on_progress=report, channel=channel)
                return SceneBand(
                    polarization=channel,
                    filename=node.name,
                    size_bytes=size,
                    checksum_sha256=await asyncio.to_thread(sha256_file, path),
                    source_url=url,
                    is_cog=node.is_cog,
                )

        bands = await asyncio.gather(
            *(fetch(channel, node) for channel, node in sorted(selected.items()))
        )
        if not any(band.is_cog for band in bands):
            notes.append(
                "No Cloud-Optimised variant was available; the original SAFE measurement "
                "files were downloaded instead."
            )

        bundle = SceneBundle(
            product_id=record.product_id,
            provider=self.name,
            bands=tuple(bands),
            data_provenance=DataProvenance.REAL,
            notes=tuple(notes),
            extra={"product_uuid": product_uuid, "safe_name": safe_name},
        )
        await asyncio.to_thread(write_bundle, target, bundle)
        if progress is not None:
            await progress(fraction=1.0, message="download complete")
        log.info(
            "cdse_download_complete",
            product_id=record.product_id,
            bands=[band.polarization for band in bands],
            total_bytes=bundle.total_bytes,
        )
        return bundle_stored_object(target, bundle)

    # ------------------------------------------------------------------ internals
    async def _resolve_download_product(self, record: SceneRecord) -> tuple[str, str, list[str]]:
        """Prefer the ``-COG`` twin of a GRD; fall back to the original SAFE.

        CDSE stores each GRD twice.  The COG copy is both smaller and window-readable,
        so it is what we want — but its presence is not guaranteed, and a missing twin
        must degrade to the original rather than fail the case.
        """
        notes: list[str] = []
        uuid = str(record.provider_ref.get("uuid") or record.provider_ref.get("Id") or "")
        safe_name = str(record.provider_ref.get("name") or record.product_id)
        if not uuid:
            raise ProviderError(
                f"Scene {record.product_id} carries no CDSE product UUID, so it cannot "
                "be downloaded. Re-run the catalogue search.",
                provider=PROVIDER,
            )
        if (record.product_type or "").upper().endswith(COG_SUFFIX):
            return uuid, safe_name, notes

        stem = safe_name.removesuffix(".SAFE")
        try:
            payload = await self._get_json(
                f"{self._catalogue_url}/Products",
                params={
                    "$filter": (
                        f"Collection/Name eq '{DEFAULT_COLLECTION}' "
                        f"and contains(Name,'{_odata_literal(stem)}')"
                    ),
                    "$expand": "Attributes",
                    "$top": "10",
                },
            )
        except ProviderError as exc:
            notes.append(f"COG lookup failed ({exc.message}); using the original product.")
            return uuid, safe_name, notes

        for product in payload.get("value") or []:
            attributes = product_attributes(product)
            product_type = str(attributes.get("productType") or "")
            if product_type.upper().endswith(COG_SUFFIX):
                cog_uuid = str(product.get("Id") or "")
                cog_name = str(product.get("Name") or safe_name)
                if cog_uuid:
                    notes.append(
                        f"Downloaded the Cloud-Optimised twin ({product_type}) rather than "
                        "the full SAFE archive."
                    )
                    return cog_uuid, cog_name, notes

        notes.append(
            "No Cloud-Optimised twin was listed for this product; the original SAFE "
            "measurement files were used."
        )
        return uuid, safe_name, notes

    async def _measurement_nodes(self, uuid: str, safe_name: str) -> list[MeasurementNode]:
        url = (
            f"{self._catalogue_url}/Products({uuid})"
            f"/Nodes({_node_segment(safe_name)})/Nodes(measurement)/Nodes"
        )
        payload = await self._get_json(url, authenticated=True)
        entries = payload.get("result")
        if not isinstance(entries, list):
            entries = payload.get("value")
        if not isinstance(entries, list):
            raise ProviderError(
                "The Copernicus node listing had an unrecognised shape, so the "
                "measurement files could not be enumerated.",
                provider=PROVIDER,
                keys=sorted(payload)[:10],
            )
        nodes = [
            MeasurementNode(name=str(entry.get("Name") or ""), size_bytes=_as_int(entry, "Length"))
            for entry in entries
            if isinstance(entry, dict) and entry.get("Name")
        ]
        return [node for node in nodes if node.name.lower().endswith((".tiff", ".tif"))]

    def _node_value_url(self, uuid: str, safe_name: str, filename: str) -> str:
        return (
            f"{self._download_url}/Products({uuid})"
            f"/Nodes({_node_segment(safe_name)})/Nodes(measurement)"
            f"/Nodes({_node_segment(filename)})/$value"
        )

    async def _get_json(
        self,
        url: str,
        *,
        params: dict[str, str] | None = None,
        authenticated: bool = False,
    ) -> dict[str, Any]:
        headers: dict[str, str] = {"Accept": "application/json"}
        if authenticated:
            headers["Authorization"] = f"Bearer {await self._tokens.access_token()}"
        response = await self._send(url, headers=headers, params=params)
        if response.status_code == 401 and authenticated:
            self._tokens.invalidate()
            headers["Authorization"] = f"Bearer {await self._tokens.access_token()}"
            response = await self._send(url, headers=headers, params=params)
        _raise_for_status(response, url)
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderError(
                "The Copernicus catalogue returned a non-JSON response.",
                provider=PROVIDER,
                url=url,
            ) from exc
        if not isinstance(payload, dict):
            raise ProviderError(
                "The Copernicus catalogue returned an unexpected payload.",
                provider=PROVIDER,
                url=url,
            )
        return payload

    async def _send(
        self,
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        try:
            return await self._http().get(url, headers=headers, params=params)
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(
                f"Could not reach the Copernicus catalogue: {exc}", provider=PROVIDER, url=url
            ) from exc

    async def _open_stream(self, url: str, headers: dict[str, str]) -> httpx.Response:
        """GET with manual redirect following so ``Authorization`` is retained.

        httpx drops credentials across hosts by default, which breaks the zipper's
        redirect to its storage front-end.  This is the ``curl --location-trusted``
        behaviour AD-08 requires; the URLs are provider-controlled, so it is safe here
        and nowhere else.
        """
        client = self._http()
        current = url
        for _ in range(MAX_REDIRECTS):
            request = client.build_request("GET", current, headers=headers)
            try:
                response = await client.send(request, stream=True)
            except httpx.HTTPError as exc:
                raise ProviderUnavailableError(
                    f"Transfer from Copernicus failed: {exc}", provider=PROVIDER, url=current
                ) from exc
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("location")
                await response.aclose()
                if not location:
                    raise ProviderError(
                        "Copernicus returned a redirect without a Location header.",
                        provider=PROVIDER,
                        url=current,
                    )
                current = str(httpx.URL(current).join(location))
                continue
            return response
        raise ProviderError(
            f"Copernicus redirected more than {MAX_REDIRECTS} times.",
            provider=PROVIDER,
            url=url,
        )

    async def _probe_size(self, url: str) -> int | None:
        """Total size of a node.

        ``HEAD`` answers 405 on this endpoint, so the probe is a one-byte ranged GET and
        the answer is read out of ``Content-Range``.
        """
        headers = {
            "Authorization": f"Bearer {await self._tokens.access_token()}",
            "Range": "bytes=0-0",
        }
        try:
            response = await self._open_stream(url, headers)
        except ProviderUnavailableError as exc:
            # An unknown size only costs the resume check; it must not fail the download.
            log.warning("cdse_size_probe_failed", url=url, error=exc.message)
            return None
        try:
            if response.status_code == 401:
                self._tokens.invalidate()
                await response.aclose()
                headers["Authorization"] = f"Bearer {await self._tokens.access_token()}"
                response = await self._open_stream(url, headers)
            _raise_for_status(response, url)
            content_range = response.headers.get("content-range", "")
            if "/" in content_range:
                total = content_range.rsplit("/", 1)[-1].strip()
                if total.isdigit():
                    return int(total)
            length = response.headers.get("content-length")
            if length and length.isdigit() and response.status_code == 200:
                return int(length)
        finally:
            await response.aclose()
        return None

    async def _download_to(
        self,
        url: str,
        path: Path,
        *,
        on_progress: Any = None,
        channel: str = "",
    ) -> int:
        """Stream a node to disk, resuming a partial file after a dropped connection."""
        total = await self._probe_size(url)
        for attempt in range(1, MAX_TRANSFER_ATTEMPTS + 1):
            have = await asyncio.to_thread(_file_size, path)
            if total is not None and have >= total > 0:
                return have
            headers = {"Authorization": f"Bearer {await self._tokens.access_token()}"}
            if have:
                # Resume where the dropped transfer stopped rather than starting over.
                headers["Range"] = f"bytes={have}-"

            response: httpx.Response | None = None
            try:
                response = await self._open_stream(url, headers)
                if response.status_code == 401:
                    self._tokens.invalidate()
                    continue
                if response.status_code == 416 and total is not None and have >= total:
                    return have
                if response.status_code == 200 and have:
                    # The server ignored the range; restart cleanly rather than
                    # appending a second copy of the file to the first.
                    await asyncio.to_thread(_truncate, path)
                    have = 0
                _raise_for_status(response, url)
                have = await self._stream_to_file(
                    response, path, have, on_progress=on_progress, channel=channel
                )
            except ProviderUnavailableError:
                if attempt == MAX_TRANSFER_ATTEMPTS:
                    raise
                log.warning("cdse_transfer_retry", url=url, attempt=attempt, bytes_downloaded=have)
                await asyncio.sleep(min(8.0, 2.0**attempt))
                continue
            finally:
                if response is not None:
                    await response.aclose()

            if total is None or have >= total:
                return have
            log.warning("cdse_transfer_short", url=url, expected=total, received=have)
        raise ProviderUnavailableError(
            f"Could not download {path.name} from Copernicus after "
            f"{MAX_TRANSFER_ATTEMPTS} attempts.",
            provider=PROVIDER,
            url=url,
        )

    async def _stream_to_file(
        self,
        response: httpx.Response,
        path: Path,
        have: int,
        *,
        on_progress: Any,
        channel: str,
    ) -> int:
        handle = await asyncio.to_thread(_open_append, path)
        try:
            async for chunk in response.aiter_bytes(DOWNLOAD_CHUNK_BYTES):
                await asyncio.to_thread(handle.write, chunk)
                have += len(chunk)
                if on_progress is not None:
                    await on_progress(channel, have)
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(
                f"The transfer from Copernicus was interrupted: {exc}",
                provider=PROVIDER,
                url=str(response.request.url),
            ) from exc
        finally:
            await asyncio.to_thread(handle.close)
        return have


# --------------------------------------------------------------------------- parsing
def build_odata_filter(
    *,
    wkt: str,
    start: datetime,
    end: datetime,
    product_type: str = DEFAULT_PRODUCT_TYPE,
    collection: str = DEFAULT_COLLECTION,
) -> str:
    """The OData ``$filter`` for a Sentinel-1 AOI/window query (AD-07)."""
    return (
        f"Collection/Name eq '{collection}'"
        " and Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType'"
        f" and att/OData.CSC.StringAttribute/Value eq '{_odata_literal(product_type)}')"
        f" and OData.CSC.Intersects(area=geography'SRID=4326;{wkt}')"
        f" and ContentDate/Start gt {_odata_datetime(start)}"
        f" and ContentDate/Start lt {_odata_datetime(end)}"
    )


def aoi_to_wkt_polygon(
    aoi_geojson: dict[str, Any], *, max_vertices: int = MAX_FILTER_VERTICES
) -> str:
    """A closed WKT polygon small enough to sit inside an OData filter.

    An unclosed ring is rejected by the service, and a 5 000-vertex coastline AOI
    produces a filter the gateway refuses, so the ring is simplified — outward, via the
    convex hull, so the query never *loses* coverage.
    """
    geometry: BaseGeometry = parse_geojson_geometry(aoi_geojson)
    if geometry.is_empty:
        raise ProviderError("The area of interest is empty.", provider=PROVIDER)
    polygon = geometry if geometry.geom_type == "Polygon" else geometry.convex_hull
    coords = list(getattr(polygon, "exterior", polygon).coords)
    if len(coords) > max_vertices:
        polygon = polygon.convex_hull
        coords = list(polygon.exterior.coords)
    if len(coords) > max_vertices:
        polygon = polygon.envelope
        coords = list(polygon.exterior.coords)
    if coords[0] != coords[-1]:
        coords.append(coords[0])
    body = ", ".join(f"{lon:.6f} {lat:.6f}" for lon, lat in coords)
    return f"POLYGON(({body}))"


def product_attributes(product: dict[str, Any]) -> dict[str, Any]:
    """Flatten ``$expand=Attributes`` into a plain mapping.

    Values arrive typed — ``StringAttribute``, ``IntegerAttribute``,
    ``DateTimeOffsetAttribute`` — and the type matters: ``relativeOrbitNumber`` is an
    integer, so a string comparison against it silently matches nothing.
    """
    attributes: dict[str, Any] = {}
    for entry in product.get("Attributes") or []:
        if not isinstance(entry, dict):
            continue
        name = entry.get("Name")
        if not isinstance(name, str):
            continue
        attributes[name] = entry.get("Value")
    return attributes


def parse_product(product: dict[str, Any]) -> SceneRecord:
    attributes = product_attributes(product)
    name = str(product.get("Name") or product.get("Id") or "")
    uuid = str(product.get("Id") or "")

    polarizations = parse_polarisations(attributes.get("polarisationChannels"))
    orbit_direction = attributes.get("orbitDirection")
    footprint = product.get("GeoFootprint")
    if not isinstance(footprint, dict):
        footprint = wkt_footprint_to_geojson(product.get("Footprint"))

    return SceneRecord(
        product_id=name,
        provider=PROVIDER,
        acquisition_time=parse_odata_datetime(
            (product.get("ContentDate") or {}).get("Start") if product.get("ContentDate") else None
        ),
        footprint_geojson=footprint,
        mission=str(attributes.get("platformShortName") or "SENTINEL-1"),
        platform=_platform(attributes),
        product_type=str(attributes.get("productType") or DEFAULT_PRODUCT_TYPE),
        sensor_mode=_sensor_mode(attributes),
        polarizations=polarizations,
        orbit_direction=str(orbit_direction).upper() if orbit_direction else None,
        relative_orbit=_optional_int(attributes.get("relativeOrbitNumber")),
        absolute_orbit=_optional_int(attributes.get("orbitNumber")),
        size_bytes=_as_int(product, "ContentLength") or None,
        resolution_m=10.0,
        provider_ref={
            "uuid": uuid,
            "name": name,
            "online": product.get("Online"),
            "origin_date": product.get("OriginDate"),
            "s3_path": product.get("S3Path"),
            "product_type": attributes.get("productType"),
        },
        data_provenance=DataProvenance.REAL,
    )


def parse_polarisations(value: Any) -> tuple[str, ...]:
    """``polarisationChannels`` is ``"VV&VH"`` — one ampersand-joined string."""
    if value is None:
        return ()
    if isinstance(value, list | tuple):
        return tuple(str(item).strip().upper() for item in value if str(item).strip())
    parts = re.split(r"[&,\s]+", str(value))
    return tuple(part.strip().upper() for part in parts if part.strip())


def parse_odata_datetime(value: Any) -> datetime:
    if not value:
        return datetime(1970, 1, 1, tzinfo=UTC)
    text = str(value).replace("Z", "+00:00")
    # OData emits more than six fractional digits often enough to matter.
    match = re.match(r"^(.*\.\d{6})\d+(.*)$", text)
    if match:
        text = f"{match.group(1)}{match.group(2)}"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return datetime(1970, 1, 1, tzinfo=UTC)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def wkt_footprint_to_geojson(value: Any) -> dict[str, Any]:
    """CDSE's ``Footprint`` is ``geography'SRID=4326;POLYGON((...))'``."""
    if not value:
        return {"type": "Polygon", "coordinates": []}
    text = str(value)
    if ";" in text:
        text = text.split(";", 1)[1]
    text = text.strip().rstrip("'")
    try:
        from shapely import wkt as shapely_wkt

        return dict(mapping(shapely_wkt.loads(text)))
    except Exception:  # a malformed footprint must not fail the whole search
        log.warning("cdse_footprint_unparsable", footprint=str(value)[:120])
        return {"type": "Polygon", "coordinates": []}


def select_band_nodes(
    nodes: list[MeasurementNode], wanted: tuple[str, ...]
) -> dict[str, MeasurementNode]:
    """One node per requested polarisation, preferring the Cloud-Optimised copy."""
    chosen: dict[str, MeasurementNode] = {}
    for node in nodes:
        channel = node.polarization
        if channel is None or channel not in wanted:
            continue
        current = chosen.get(channel)
        if current is None or (node.is_cog and not current.is_cog):
            chosen[channel] = node
    return chosen


# --------------------------------------------------------------------------- helpers
def _sensor_mode(attributes: dict[str, Any]) -> str | None:
    mode = attributes.get("operationalMode") or attributes.get("swathIdentifier")
    return str(mode) if mode else None


def _platform(attributes: dict[str, Any]) -> str | None:
    short = str(attributes.get("platformShortName") or "").upper()
    serial = str(attributes.get("platformSerialIdentifier") or "").upper()
    if short.startswith("SENTINEL") and serial:
        return f"S1{serial}"
    return serial or None


def _odata_literal(value: str) -> str:
    return value.replace("'", "''")


def _odata_datetime(value: datetime) -> str:
    return ensure_utc(value).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _node_segment(name: str) -> str:
    if not _SAFE_NAME.match(name):
        raise ProviderError(
            f"Refusing to build a node path from an unexpected name: {name!r}",
            provider=PROVIDER,
        )
    return name


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_int(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _raise_for_status(response: httpx.Response, url: str) -> None:
    status = response.status_code
    if status < 400:
        return
    if status == 401:
        from spilltrace.core.errors import ProviderAuthError

        raise ProviderAuthError(
            "Copernicus rejected the access token for this request.",
            provider=PROVIDER,
            url=url,
            status_code=status,
        )
    if status == 404:
        raise ProviderError(
            "Copernicus has no such product or node (HTTP 404).",
            provider=PROVIDER,
            url=url,
            status_code=status,
        )
    if status == 405:
        raise ProviderError(
            "Copernicus refused the HTTP method (405). This endpoint accepts ranged GET "
            "only — HEAD is not supported.",
            provider=PROVIDER,
            url=url,
            status_code=status,
        )
    if status in (429, 503):
        raise ProviderUnavailableError(
            f"Copernicus is throttling or unavailable (HTTP {status}).",
            provider=PROVIDER,
            url=url,
            status_code=status,
        )
    raise ProviderError(
        f"Copernicus returned HTTP {status}.", provider=PROVIDER, url=url, status_code=status
    )


def _file_size(path: Path) -> int:
    return path.stat().st_size if path.exists() else 0


def _truncate(path: Path) -> None:
    if path.exists():
        path.unlink()


def _open_append(path: Path) -> Any:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.open("ab")


__all__ = [
    "CATALOGUE_URL",
    "MAX_CONCURRENT_DOWNLOADS",
    "ZIPPER_URL",
    "CDSECatalogue",
    "MeasurementNode",
    "aoi_to_wkt_polygon",
    "build_odata_filter",
    "parse_odata_datetime",
    "parse_polarisations",
    "parse_product",
    "product_attributes",
    "select_band_nodes",
    "wkt_footprint_to_geojson",
]
