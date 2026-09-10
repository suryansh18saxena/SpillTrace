"""Case endpoints (FR-001, UI-002, UI-003)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status
from geoalchemy2.shape import to_shape
from shapely.geometry import mapping

from spilltrace.api.auth import CurrentAdmin, CurrentUser
from spilltrace.api.deps import (
    FromQuery,
    PaginationDep,
    SearchQuery,
    SessionDep,
    SettingsDep,
    StatusQuery,
    ToQuery,
)
from spilltrace.api.schemas.cases import CaseCreate, CaseDetailOut, CaseOut, CaseUpdate
from spilltrace.api.schemas.common import PageResponse
from spilltrace.core.disclaimers import SYNTHETIC_DATA_NOTICE
from spilltrace.core.enums import CaseStatus, DataProvenance
from spilltrace.core.errors import ConflictError
from spilltrace.core.geometry import geodesic_area_km2, validate_polygon
from spilltrace.core.time import validate_time_window
from spilltrace.db.models import Case
from spilltrace.db.repositories.cases import CaseRepository
from spilltrace.logging import get_logger

router = APIRouter(prefix="/api/v1/cases", tags=["cases"])
log = get_logger(__name__)


def _to_out(case: Case) -> CaseOut:
    data = {
        **{c.name: getattr(case, c.name) for c in case.__table__.columns},
        "aoi": mapping(to_shape(case.aoi)),
        "owner": case.owner if "owner" in case.__dict__ else None,
    }
    return CaseOut.model_validate(data)


@router.post("", response_model=CaseDetailOut, status_code=status.HTTP_201_CREATED)
async def create_case(
    body: CaseCreate, user: CurrentUser, session: SessionDep, settings: SettingsDep
) -> CaseDetailOut:
    """Create an investigation.

    The AOI and time window are validated here rather than downstream because every
    later stage derives its query parameters from them; an invalid AOI would otherwise
    surface as a confusing provider error three stages later.
    """
    aoi = validate_polygon(body.aoi.model_dump(), max_area_km2=settings.max_aoi_km2, field="aoi")
    start, end = validate_time_window(
        body.start_time, body.end_time, max_days=settings.max_time_window_days, field="case window"
    )
    repo = CaseRepository(session)
    case = await repo.create(
        owner=user,
        title=body.title,
        description=body.description,
        aoi=aoi,
        start_time=start,
        end_time=end,
    )
    await session.commit()
    await session.refresh(case)
    log.info("case_created", case_id=str(case.id), case_ref=case.case_ref)
    return CaseDetailOut(
        **_to_out(case).model_dump(),
        aoi_area_km2=round(geodesic_area_km2(aoi), 2),
        counts=await repo.artifact_counts(case.id),
    )


@router.get("", response_model=PageResponse[CaseOut])
async def list_cases(
    user: CurrentUser,
    session: SessionDep,
    pagination: PaginationDep,
    status_filter: StatusQuery = None,
    q: SearchQuery = None,
    created_from: FromQuery = None,
    created_to: ToQuery = None,
    include_archived: bool = False,
) -> PageResponse[CaseOut]:
    page = await CaseRepository(session).list_for_user(
        user,
        limit=pagination.limit,
        offset=pagination.offset,
        status=status_filter,
        query=q,
        created_from=created_from,
        created_to=created_to,
        include_archived=include_archived,
    )
    return PageResponse[CaseOut](
        items=[_to_out(c) for c in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{case_id}", response_model=CaseDetailOut)
async def get_case(case_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> CaseDetailOut:
    repo = CaseRepository(session)
    case = await repo.get_for_user(case_id, user)
    aoi = to_shape(case.aoi)
    return CaseDetailOut(
        **_to_out(case).model_dump(),
        aoi_area_km2=round(geodesic_area_km2(aoi), 2),
        counts=await repo.artifact_counts(case.id),
        notice=(
            SYNTHETIC_DATA_NOTICE if case.data_provenance != DataProvenance.REAL.value else None
        ),
    )


@router.patch("/{case_id}", response_model=CaseDetailOut)
async def update_case(
    case_id: uuid.UUID,
    body: CaseUpdate,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> CaseDetailOut:
    repo = CaseRepository(session)
    case = await repo.get_for_user(case_id, user)

    aoi = (
        validate_polygon(body.aoi.model_dump(), max_area_km2=settings.max_aoi_km2, field="aoi")
        if body.aoi is not None
        else None
    )
    start, end = case.start_time, case.end_time
    if body.start_time is not None or body.end_time is not None:
        start, end = validate_time_window(
            body.start_time or case.start_time,
            body.end_time or case.end_time,
            max_days=settings.max_time_window_days,
            field="case window",
        )

    await repo.update(
        case,
        title=body.title,
        description=body.description,
        aoi=aoi,
        start_time=start if body.start_time is not None else None,
        end_time=end if body.end_time is not None else None,
    )
    await session.commit()
    await session.refresh(case)
    return CaseDetailOut(
        **_to_out(case).model_dump(),
        aoi_area_km2=round(geodesic_area_km2(to_shape(case.aoi)), 2),
        counts=await repo.artifact_counts(case.id),
    )


@router.post("/{case_id}/archive", response_model=CaseOut)
async def archive_case(case_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> CaseOut:
    repo = CaseRepository(session)
    case = await repo.get_for_user(case_id, user)
    if case.status == CaseStatus.RUNNING.value:
        raise ConflictError("A case cannot be archived while its pipeline is running.")
    await repo.set_status(case, CaseStatus.ARCHIVED)
    await session.commit()
    return _to_out(case)


@router.delete("/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_case(case_id: uuid.UUID, admin: CurrentAdmin, session: SessionDep) -> None:
    """Permanently delete a case and every artifact derived from it.

    Restricted to administrators: for an evidence system, destroying the chain is a
    privileged act, and archiving is the normal way to retire a case.
    """
    repo = CaseRepository(session)
    case = await repo.get_for_user(case_id, admin)
    await repo.delete(case)
    await session.commit()
    log.warning("case_deleted", case_id=str(case_id), by=str(admin.id))


__all__ = ["router"]
