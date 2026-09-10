"""The Copernicus adapter, against recorded HTTP rather than the live service.

Nothing here needs credentials or a network.  What is tested is the set of things that
AD-06/AD-07/AD-08 say the live APIs actually do, and that are silently wrong otherwise:
the OData filter shape, the ampersand-joined polarisation string, the integer-typed
relative orbit, the 405 on HEAD, redirects that must keep the Authorization header, and
resuming a dropped transfer.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from spilltrace.adapters.satellite import build_satellite_catalogue
from spilltrace.adapters.satellite.cdse import (
    CATALOGUE_URL,
    MAX_CONCURRENT_DOWNLOADS,
    ZIPPER_URL,
    CDSECatalogue,
    MeasurementNode,
    aoi_to_wkt_polygon,
    build_odata_filter,
    parse_odata_datetime,
    parse_polarisations,
    parse_product,
    select_band_nodes,
    wkt_footprint_to_geojson,
)
from spilltrace.adapters.satellite.cdse_auth import (
    CDSE_IDENTITY_URL,
    CDSECredentials,
    CDSETokenManager,
    TokenState,
)
from spilltrace.config import Settings
from spilltrace.core.errors import (
    ProviderAuthError,
    ProviderError,
    ProviderNotConfiguredError,
    ProviderUnavailableError,
)

AOI = {
    "type": "Polygon",
    "coordinates": [[[68.6, 21.9], [70.4, 21.9], [70.4, 23.1], [68.6, 23.1], [68.6, 21.9]]],
}
START = datetime(2026, 8, 13, tzinfo=UTC)
END = START + timedelta(days=3)
CREDENTIALS = CDSECredentials(username="analyst@example.org", password="not-a-real-password")

UUID_A = "11111111-2222-3333-4444-555555555555"
UUID_COG = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
NAME_A = "S1A_IW_GRDH_1SDV_20260814T011200_20260814T011229_054321_06ABCD_1234.SAFE"
NAME_C = "S1C_IW_GRDH_1SDV_20260814T011500_20260814T011529_004321_00ABCD_5678.SAFE"


def _attribute(name: str, value: object, kind: str = "String") -> dict[str, object]:
    return {
        "@odata.type": f"#OData.CSC.{kind}Attribute",
        "Name": name,
        "Value": value,
        "ValueType": kind,
    }


def _product(name: str, uuid: str, platform: str, product_type: str = "IW_GRDH_1S") -> dict:
    return {
        "@odata.mediaContentType": "application/octet-stream",
        "Id": uuid,
        "Name": name,
        "ContentLength": 1_723_456_789,
        "Online": True,
        "S3Path": f"/eodata/Sentinel-1/SAR/GRD/2026/08/14/{name}",
        "ContentDate": {"Start": "2026-08-14T01:12:00.123456789Z", "End": "2026-08-14T01:12:29Z"},
        "Footprint": (
            "geography'SRID=4326;POLYGON((68.5 21.8,70.5 21.8,70.5 23.2,68.5 23.2,68.5 21.8))'"
        ),
        "GeoFootprint": {
            "type": "Polygon",
            "coordinates": [[[68.5, 21.8], [70.5, 21.8], [70.5, 23.2], [68.5, 23.2], [68.5, 21.8]]],
        },
        "Attributes": [
            _attribute("productType", product_type),
            _attribute("platformShortName", "SENTINEL-1"),
            _attribute("platformSerialIdentifier", platform),
            _attribute("operationalMode", "IW"),
            # CONFIRMED: one ampersand-joined string, not a list.
            _attribute("polarisationChannels", "VV&VH"),
            # CONFIRMED: upper-case in OData, lower-case in STAC.
            _attribute("orbitDirection", "DESCENDING"),
            # CONFIRMED: an Integer attribute, not a String one.
            _attribute("relativeOrbitNumber", 107, kind="Integer"),
            _attribute("orbitNumber", 54321, kind="Integer"),
        ],
    }


VV_TIFF = f"{NAME_A[:-5].lower()}-vv-001-cog.tiff"
VH_TIFF = f"{NAME_A[:-5].lower()}-vh-001-cog.tiff"
VV_BYTES = bytes(range(256)) * 40
VH_BYTES = bytes(range(255, -1, -1)) * 30


class Recorder:
    """A scripted CDSE, recording every request so the tests can assert on them."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.token_calls: list[dict[str, str]] = []
        self.tokens_issued = 0
        self.fail_first_value_get = False
        self.reject_first_token = False
        self.node_unauthorised_once = False
        self.include_cog_twin = True
        self._value_attempts = 0

    # -- helpers ---------------------------------------------------------------
    def _token(self, request: httpx.Request) -> httpx.Response:
        form = dict(httpx.QueryParams(request.content.decode()))
        self.token_calls.append(form)
        if self.reject_first_token and len(self.token_calls) == 1:
            return httpx.Response(
                400, json={"error": "invalid_grant", "error_description": "Invalid user"}
            )
        if form.get("grant_type") == "refresh_token" and form.get("refresh_token") == "stale":
            return httpx.Response(
                400, json={"error": "invalid_grant", "error_description": "Token is not active"}
            )
        self.tokens_issued += 1
        return httpx.Response(
            200,
            json={
                "access_token": f"access-{self.tokens_issued}",
                "expires_in": 600,
                "refresh_expires_in": 3600,
                "refresh_token": f"refresh-{self.tokens_issued}",
                "token_type": "Bearer",
            },
        )

    def _payload_for(self, url: str) -> bytes:
        return VV_BYTES if "-vv-" in url else VH_BYTES

    # -- transport -------------------------------------------------------------
    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)

        if url.startswith(CDSE_IDENTITY_URL):
            return self._token(request)

        if request.method == "HEAD":
            # CONFIRMED: the download endpoint answers 405 to HEAD.
            return httpx.Response(405)

        if url.startswith(f"{CATALOGUE_URL}/Products?"):
            odata_filter = request.url.params.get("$filter", "")
            if "contains(Name" in odata_filter:
                twin = _product(NAME_A, UUID_COG, "A", product_type="IW_GRDH_1S-COG")
                return httpx.Response(200, json={"value": [twin] if self.include_cog_twin else []})
            return httpx.Response(
                200,
                json={
                    "value": [
                        _product(NAME_A, UUID_A, "A"),
                        _product(NAME_C, "99999999-2222-3333-4444-555555555555", "C"),
                    ]
                },
            )

        if url.endswith("/Nodes(measurement)/Nodes"):
            if self.node_unauthorised_once:
                self.node_unauthorised_once = False
                return httpx.Response(401, json={"detail": "expired"})
            return httpx.Response(
                200,
                json={
                    "result": [
                        {"Id": VV_TIFF, "Name": VV_TIFF, "Length": len(VV_BYTES)},
                        {"Id": VH_TIFF, "Name": VH_TIFF, "Length": len(VH_BYTES)},
                        {"Id": "annotation.xml", "Name": "annotation.xml", "Length": 10},
                    ]
                },
            )

        if url.endswith("/$value"):
            if "unknown-file" in url:
                return httpx.Response(404, json={"detail": "Not found"})
            if url.startswith(ZIPPER_URL):
                # The zipper redirects to a storage front-end; the redirect must be
                # followed with the Authorization header intact.
                return httpx.Response(
                    307, headers={"location": url.replace(ZIPPER_URL, "https://download.example")}
                )
            payload = self._payload_for(url)
            if self.fail_first_value_get:
                self._value_attempts += 1
                if self._value_attempts == 1:
                    raise httpx.ReadError("connection reset by peer")
            range_header = request.headers.get("range", "")
            if range_header == "bytes=0-0":
                return httpx.Response(
                    206,
                    content=payload[:1],
                    headers={"content-range": f"bytes 0-0/{len(payload)}"},
                )
            if range_header.startswith("bytes="):
                start = int(range_header.removeprefix("bytes=").split("-")[0])
                return httpx.Response(
                    206,
                    content=payload[start:],
                    headers={"content-range": f"bytes {start}-{len(payload) - 1}/{len(payload)}"},
                )
            return httpx.Response(200, content=payload)

        return httpx.Response(404, json={"detail": f"unexpected {url}"})


def _catalogue(recorder: Recorder, **kwargs: object) -> CDSECatalogue:
    client = httpx.AsyncClient(transport=httpx.MockTransport(recorder), follow_redirects=False)
    return CDSECatalogue(CREDENTIALS, client=client, **kwargs)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- filter
def test_odata_filter_matches_the_documented_shape() -> None:
    odata = build_odata_filter(wkt=aoi_to_wkt_polygon(AOI), start=START, end=END)
    assert "Collection/Name eq 'SENTINEL-1'" in odata
    assert "att/Name eq 'productType'" in odata
    assert "att/OData.CSC.StringAttribute/Value eq 'IW_GRDH_1S'" in odata
    assert "OData.CSC.Intersects(area=geography'SRID=4326;POLYGON((" in odata
    assert "ContentDate/Start gt 2026-08-13T00:00:00.000Z" in odata
    assert "ContentDate/Start lt 2026-08-16T00:00:00.000Z" in odata


def test_the_search_polygon_is_closed() -> None:
    """CDSE rejects an unclosed ring, and an open AOI is the easy mistake."""
    wkt = aoi_to_wkt_polygon(
        {"type": "Polygon", "coordinates": [[[68.6, 21.9], [70.4, 21.9], [70.4, 23.1]]]}
    )
    coords = wkt.removeprefix("POLYGON((").removesuffix("))").split(", ")
    assert coords[0] == coords[-1]


def test_a_huge_ring_is_simplified_outward_never_inward() -> None:
    import math

    ring = [
        [69.5 + 0.5 * math.cos(i / 100 * 2 * math.pi), 22.5 + 0.5 * math.sin(i / 100 * 2 * math.pi)]
        for i in range(100)
    ]
    ring.append(ring[0])
    wkt = aoi_to_wkt_polygon({"type": "Polygon", "coordinates": [ring]}, max_vertices=10)
    assert wkt.count(",") < 10
    from shapely import wkt as shapely_wkt
    from shapely.geometry import shape

    assert shapely_wkt.loads(wkt).covers(shape({"type": "Polygon", "coordinates": [ring]}))


def test_an_empty_aoi_is_rejected() -> None:
    with pytest.raises(ProviderError, match="empty"):
        aoi_to_wkt_polygon({"type": "Polygon", "coordinates": []})


# --------------------------------------------------------------------------- parsing
def test_polarisation_channels_are_ampersand_joined() -> None:
    assert parse_polarisations("VV&VH") == ("VV", "VH")
    assert parse_polarisations("VV") == ("VV",)
    assert parse_polarisations(["VV", "VH"]) == ("VV", "VH")
    assert parse_polarisations(None) == ()


def test_product_attributes_are_typed_correctly() -> None:
    record = parse_product(_product(NAME_A, UUID_A, "A"))
    assert record.product_id == NAME_A
    assert record.platform == "S1A"
    assert record.polarizations == ("VV", "VH")
    assert record.orbit_direction == "DESCENDING"
    assert record.relative_orbit == 107  # Integer attribute, not a string
    assert isinstance(record.relative_orbit, int)
    assert record.absolute_orbit == 54321
    assert record.provider_ref["uuid"] == UUID_A
    assert record.size_bytes == 1_723_456_789


def test_nanosecond_timestamps_are_parsed() -> None:
    parsed = parse_odata_datetime("2026-08-14T01:12:00.123456789Z")
    assert parsed.tzinfo is not None
    assert parsed.year == 2026 and parsed.microsecond == 123456


def test_an_unparsable_footprint_degrades_instead_of_raising() -> None:
    assert wkt_footprint_to_geojson("not a polygon")["coordinates"] == []
    parsed = wkt_footprint_to_geojson("geography'SRID=4326;POLYGON((0 0,1 0,1 1,0 1,0 0))'")
    assert parsed["type"] == "Polygon"


# --------------------------------------------------------------------------- search
async def test_search_returns_both_s1a_and_s1c() -> None:
    """AD-07's whole point: a STAC product:type filter would drop the S1C scene."""
    recorder = Recorder()
    catalogue = _catalogue(recorder)
    records = await catalogue.search(aoi_geojson=AOI, start=START, end=END)
    assert [r.platform for r in records] == ["S1A", "S1C"]
    assert {r.product_type for r in records} == {"IW_GRDH_1S"}
    await catalogue.aclose()


async def test_search_does_not_need_a_token() -> None:
    """The OData catalogue is open; only the download service is authenticated."""
    recorder = Recorder()
    catalogue = _catalogue(recorder)
    await catalogue.search(aoi_geojson=AOI, start=START, end=END)
    assert recorder.token_calls == []
    await catalogue.aclose()


async def test_a_server_error_during_search_is_reported_as_a_provider_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    catalogue = CDSECatalogue(CREDENTIALS, client=client)
    with pytest.raises(ProviderError, match="HTTP 500"):
        await catalogue.search(aoi_geojson=AOI, start=START, end=END)
    await catalogue.aclose()


async def test_throttling_is_reported_as_unavailable_not_as_a_bug() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="slow down")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    catalogue = CDSECatalogue(CREDENTIALS, client=client)
    with pytest.raises(ProviderUnavailableError):
        await catalogue.search(aoi_geojson=AOI, start=START, end=END)
    await catalogue.aclose()


# --------------------------------------------------------------------------- download
async def test_download_fetches_one_cog_node_per_polarisation(tmp_path: Path) -> None:
    recorder = Recorder()
    catalogue = _catalogue(recorder)
    records = await catalogue.search(aoi_geojson=AOI, start=START, end=END)
    stored = await catalogue.download(records[0], destination=str(tmp_path))

    assert (tmp_path / VV_TIFF).read_bytes() == VV_BYTES
    assert (tmp_path / VH_TIFF).read_bytes() == VH_BYTES
    assert stored.size_bytes == len(VV_BYTES) + len(VH_BYTES)

    from spilltrace.adapters.satellite.bundle import read_bundle

    bundle = read_bundle(tmp_path)
    assert {band.polarization for band in bundle.bands} == {"VV", "VH"}
    assert all(band.is_cog for band in bundle.bands)
    # The COG twin, not the original SAFE, is what was downloaded.
    assert bundle.extra["product_uuid"] == UUID_COG
    assert any("Cloud-Optimised" in note for note in bundle.notes)
    await catalogue.aclose()


async def test_head_is_never_used_and_the_size_probe_is_a_ranged_get(tmp_path: Path) -> None:
    recorder = Recorder()
    catalogue = _catalogue(recorder)
    records = await catalogue.search(aoi_geojson=AOI, start=START, end=END)
    await catalogue.download(records[0], destination=str(tmp_path))

    data_requests = [r for r in recorder.requests if not str(r.url).startswith(CDSE_IDENTITY_URL)]
    assert {r.method for r in data_requests} == {"GET"}
    probes = [r for r in recorder.requests if r.headers.get("range") == "bytes=0-0"]
    # One probe per band, each of which is then followed through the zipper's redirect.
    assert {str(r.url) for r in probes if r.url.host.endswith("copernicus.eu")} == {
        f"{ZIPPER_URL}/Products({UUID_COG})/Nodes({NAME_A})/Nodes(measurement)/Nodes({name})/$value"
        for name in (VV_TIFF, VH_TIFF)
    }
    await catalogue.aclose()


async def test_redirects_keep_the_authorization_header(tmp_path: Path) -> None:
    """The zipper redirects to storage; dropping the header there yields a 401."""
    recorder = Recorder()
    catalogue = _catalogue(recorder)
    records = await catalogue.search(aoi_geojson=AOI, start=START, end=END)
    await catalogue.download(records[0], destination=str(tmp_path))

    redirected = [r for r in recorder.requests if str(r.url).startswith("https://download.example")]
    assert redirected
    assert all(r.headers.get("authorization", "").startswith("Bearer ") for r in redirected)
    await catalogue.aclose()


async def test_a_dropped_connection_is_retried_and_the_file_completes(
    tmp_path: Path,
) -> None:
    recorder = Recorder()
    recorder.fail_first_value_get = True
    catalogue = _catalogue(recorder)
    records = await catalogue.search(aoi_geojson=AOI, start=START, end=END)
    await catalogue.download(records[0], destination=str(tmp_path))
    assert (tmp_path / VV_TIFF).read_bytes() == VV_BYTES
    await catalogue.aclose()


async def test_a_partial_file_is_resumed_with_a_range_header(tmp_path: Path) -> None:
    recorder = Recorder()
    catalogue = _catalogue(recorder)
    partial = tmp_path / VV_TIFF
    partial.write_bytes(VV_BYTES[:1000])

    url = (
        f"{ZIPPER_URL}/Products({UUID_COG})/Nodes({NAME_A})"
        f"/Nodes(measurement)/Nodes({VV_TIFF})/$value"
    )
    size = await catalogue._download_to(url, partial)

    assert size == len(VV_BYTES)
    assert partial.read_bytes() == VV_BYTES
    resumed = [r for r in recorder.requests if r.headers.get("range") == "bytes=1000-"]
    assert resumed, "the transfer restarted from zero instead of resuming"
    await catalogue.aclose()


async def test_a_missing_node_is_a_404_not_a_crash(tmp_path: Path) -> None:
    recorder = Recorder()
    catalogue = _catalogue(recorder)
    url = (
        f"{ZIPPER_URL}/Products({UUID_COG})/Nodes({NAME_A})"
        "/Nodes(measurement)/Nodes(unknown-file.tiff)/$value"
    )
    with pytest.raises(ProviderError, match="404"):
        await catalogue._download_to(url, tmp_path / "unknown-file.tiff")
    await catalogue.aclose()


async def test_a_401_on_the_node_listing_refreshes_the_token_and_retries(
    tmp_path: Path,
) -> None:
    recorder = Recorder()
    recorder.node_unauthorised_once = True
    catalogue = _catalogue(recorder)
    records = await catalogue.search(aoi_geojson=AOI, start=START, end=END)
    await catalogue.download(records[0], destination=str(tmp_path))
    assert recorder.tokens_issued >= 2
    await catalogue.aclose()


async def test_without_a_cog_twin_the_original_product_is_used_and_noted(
    tmp_path: Path,
) -> None:
    recorder = Recorder()
    recorder.include_cog_twin = False
    catalogue = _catalogue(recorder)
    records = await catalogue.search(aoi_geojson=AOI, start=START, end=END)
    await catalogue.download(records[0], destination=str(tmp_path))

    from spilltrace.adapters.satellite.bundle import read_bundle

    bundle = read_bundle(tmp_path)
    assert bundle.extra["product_uuid"] == UUID_A
    assert any("No Cloud-Optimised twin" in note for note in bundle.notes)
    await catalogue.aclose()


async def test_a_scene_without_a_uuid_cannot_be_downloaded(tmp_path: Path) -> None:
    from dataclasses import replace

    recorder = Recorder()
    catalogue = _catalogue(recorder)
    records = await catalogue.search(aoi_geojson=AOI, start=START, end=END)
    broken = replace(records[0], provider_ref={})
    with pytest.raises(ProviderError, match="no CDSE product UUID"):
        await catalogue.download(broken, destination=str(tmp_path))
    await catalogue.aclose()


def test_concurrency_is_capped_at_the_free_tier_limit() -> None:
    recorder = Recorder()
    catalogue = _catalogue(recorder, max_concurrency=32)
    assert catalogue.max_concurrency == MAX_CONCURRENT_DOWNLOADS == 4


def test_node_names_that_could_escape_the_path_are_rejected() -> None:
    recorder = Recorder()
    catalogue = _catalogue(recorder)
    with pytest.raises(ProviderError, match="unexpected name"):
        catalogue._node_value_url(UUID_A, NAME_A, "../../etc/passwd")


def test_band_selection_prefers_the_cog_copy() -> None:
    nodes = [
        MeasurementNode(name="s1a-iw-grd-vv-001.tiff", size_bytes=10),
        MeasurementNode(name="s1a-iw-grd-vv-001-cog.tiff", size_bytes=8),
        MeasurementNode(name="s1a-iw-grd-vh-001.tiff", size_bytes=7),
    ]
    chosen = select_band_nodes(nodes, ("VV", "VH"))
    assert chosen["VV"].is_cog
    assert not chosen["VH"].is_cog
    assert select_band_nodes(nodes, ("HH",)) == {}


# --------------------------------------------------------------------------- tokens
async def test_token_is_acquired_once_and_then_cached() -> None:
    recorder = Recorder()
    client = httpx.AsyncClient(transport=httpx.MockTransport(recorder))
    manager = CDSETokenManager(CREDENTIALS, client=client)
    assert await manager.access_token() == "access-1"
    assert await manager.access_token() == "access-1"
    assert len(recorder.token_calls) == 1
    assert recorder.token_calls[0]["grant_type"] == "password"
    assert recorder.token_calls[0]["client_id"] == "cdse-public"
    await client.aclose()


async def test_a_token_near_expiry_is_refreshed_not_reissued() -> None:
    """AD-06: renew at ~8 minutes of a 10-minute token, using the refresh grant."""
    recorder = Recorder()
    client = httpx.AsyncClient(transport=httpx.MockTransport(recorder))
    manager = CDSETokenManager(CREDENTIALS, client=client)
    await manager.access_token()

    state = manager.state
    assert state is not None
    state.expires_at = datetime.now(UTC) + timedelta(seconds=60)
    assert await manager.access_token() == "access-2"
    assert recorder.token_calls[-1]["grant_type"] == "refresh_token"
    await client.aclose()


async def test_an_expired_refresh_window_falls_back_to_the_password_grant() -> None:
    recorder = Recorder()
    client = httpx.AsyncClient(transport=httpx.MockTransport(recorder))
    manager = CDSETokenManager(CREDENTIALS, client=client)
    await manager.access_token()
    manager._state = TokenState(
        access_token="stale-access",
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
        refresh_token="stale",
        refresh_expires_at=datetime.now(UTC) + timedelta(seconds=600),
    )
    assert await manager.access_token() == "access-2"
    assert recorder.token_calls[-1]["grant_type"] == "password"
    await client.aclose()


async def test_bad_credentials_surface_keycloaks_own_reason() -> None:
    recorder = Recorder()
    recorder.reject_first_token = True
    client = httpx.AsyncClient(transport=httpx.MockTransport(recorder))
    manager = CDSETokenManager(CREDENTIALS, client=client)
    with pytest.raises(ProviderAuthError, match="Invalid user"):
        await manager.access_token()
    await client.aclose()


async def test_an_unreachable_identity_service_is_unavailable_not_unauthorised() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    manager = CDSETokenManager(CREDENTIALS, client=client)
    with pytest.raises(ProviderUnavailableError):
        await manager.access_token()
    await client.aclose()


async def test_concurrent_callers_open_only_one_keycloak_session() -> None:
    """The account is capped at 100 sessions; four band downloads must share one."""
    import asyncio

    recorder = Recorder()
    client = httpx.AsyncClient(transport=httpx.MockTransport(recorder))
    manager = CDSETokenManager(CREDENTIALS, client=client)
    tokens = await asyncio.gather(*(manager.access_token() for _ in range(8)))
    assert set(tokens) == {"access-1"}
    assert len(recorder.token_calls) == 1
    await client.aclose()


def test_missing_credentials_are_refused_at_construction() -> None:
    with pytest.raises(ProviderNotConfiguredError):
        CDSETokenManager(CDSECredentials(username="", password=""))


def test_the_identity_endpoint_is_the_confirmed_one() -> None:
    assert CDSE_IDENTITY_URL == (
        "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
    )


# --------------------------------------------------------------------------- factory
def _settings(**overrides: str) -> Settings:
    values: dict[str, str] = {
        "SPILLTRACE_SECRET_KEY": "unit-test-secret-key-0123456789abcdef",
        "POSTGRES_PASSWORD": "unit-test-password",
        "CDSE_USERNAME": "",
        "CDSE_PASSWORD": "",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_cdse_without_credentials_falls_back_to_the_fixture() -> None:
    catalogue = build_satellite_catalogue(_settings(SPILLTRACE_SATELLITE_PROVIDER="cdse"))
    assert catalogue.name == "fixture"


def test_cdse_with_credentials_selects_the_real_adapter() -> None:
    catalogue = build_satellite_catalogue(
        _settings(
            SPILLTRACE_SATELLITE_PROVIDER="cdse",
            CDSE_USERNAME="analyst@example.org",
            CDSE_PASSWORD="not-a-real-password",
        )
    )
    assert catalogue.name == "cdse"


def test_the_default_provider_is_the_fixture() -> None:
    assert build_satellite_catalogue(_settings()).name == "fixture"
