"""Case persistence.

Ownership filtering happens here so that a new endpoint cannot forget it (NFR-009).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import selectinload

from spilltrace.core.enums import CaseStatus, DataProvenance, UserRole
from spilltrace.core.errors import ConflictError, NotFoundError
from spilltrace.core.time import utcnow
from spilltrace.db.models import Case, User
from spilltrace.db.repositories.base import Page, Repository


class CaseRepository(Repository[Case]):
    model = Case

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _visibility(stmt: Select[Any], user: User) -> Select[Any]:
        """Admins see every case; analysts see only their own."""
        if user.role == UserRole.ADMIN.value:
            return stmt
        return stmt.where(Case.owner_id == user.id)

    @staticmethod
    def aoi_geojson(case: Case) -> dict[str, Any]:
        return mapping(to_shape(case.aoi))

    # ------------------------------------------------------------------ reads
    async def get_for_user(self, case_id: uuid.UUID, user: User) -> Case:
        stmt = self._visibility(
            select(Case).where(Case.id == case_id).options(selectinload(Case.owner)), user
        )
        case = (await self.session.execute(stmt)).scalar_one_or_none()
        if case is None:
            # Deliberately 404 rather than 403: an unauthorised caller must not be able
            # to probe which case ids exist.
            raise NotFoundError("Case not found.", case_id=str(case_id))
        return case

    async def list_for_user(
        self,
        user: User,
        *,
        limit: int,
        offset: int,
        status: str | None = None,
        query: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        include_archived: bool = False,
    ) -> Page[Case]:
        stmt = select(Case).options(selectinload(Case.owner))
        stmt = self._visibility(stmt, user)
        if status:
            stmt = stmt.where(Case.status == status)
        elif not include_archived:
            stmt = stmt.where(Case.status != CaseStatus.ARCHIVED.value)
        if query:
            pattern = f"%{query}%"
            stmt = stmt.where(
                or_(
                    Case.title.ilike(pattern),
                    Case.case_ref.ilike(pattern),
                    Case.description.ilike(pattern),
                )
            )
        if created_from:
            stmt = stmt.where(Case.created_at >= created_from)
        if created_to:
            stmt = stmt.where(Case.created_at <= created_to)
        stmt = stmt.order_by(Case.created_at.desc())
        return await self.paginate(stmt, limit=limit, offset=offset)

    async def next_case_ref(self) -> str:
        """Human-readable reference, e.g. ``ST-2026-0007``.

        Sequential within the calendar year.  Collisions are prevented by the unique
        constraint; the caller retries on conflict.
        """
        year = utcnow().year
        prefix = f"ST-{year}-"
        stmt = select(func.count()).select_from(Case).where(Case.case_ref.like(f"{prefix}%"))
        count = int((await self.session.execute(stmt)).scalar_one())
        return f"{prefix}{count + 1:04d}"

    # ------------------------------------------------------------------ writes
    async def create(
        self,
        *,
        owner: User,
        title: str,
        aoi: BaseGeometry,
        start_time: datetime,
        end_time: datetime,
        description: str | None = None,
        provenance: DataProvenance = DataProvenance.REAL,
        scenario: str | None = None,
        seed: int | None = None,
    ) -> Case:
        case = Case(
            case_ref=await self.next_case_ref(),
            title=title,
            description=description,
            status=CaseStatus.DRAFT.value,
            aoi=from_shape(aoi, srid=4326),
            start_time=start_time,
            end_time=end_time,
            owner_id=owner.id,
            data_provenance=provenance.value,
            scenario=scenario,
            seed=seed,
        )
        return await self.add(case)

    async def update(
        self,
        case: Case,
        *,
        title: str | None = None,
        description: str | None = None,
        aoi: BaseGeometry | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> Case:
        # The AOI and time window define what every downstream artifact was computed
        # from, so changing them after processing has begun would silently invalidate
        # the evidence chain.
        if (aoi is not None or start_time is not None or end_time is not None) and (
            case.status != CaseStatus.DRAFT.value
        ):
            raise ConflictError(
                "The area of interest and time window can only be changed while a case is "
                "still a draft, because downstream results are derived from them.",
                case_id=str(case.id),
                status=case.status,
            )
        if title is not None:
            case.title = title
        if description is not None:
            case.description = description
        if aoi is not None:
            case.aoi = from_shape(aoi, srid=4326)
        if start_time is not None:
            case.start_time = start_time
        if end_time is not None:
            case.end_time = end_time
        await self.session.flush()
        return case

    async def set_status(self, case: Case, status: CaseStatus) -> Case:
        case.status = status.value
        if status is CaseStatus.ARCHIVED:
            case.archived_at = utcnow()
        await self.session.flush()
        return case

    async def artifact_counts(self, case_id: uuid.UUID) -> dict[str, int]:
        """Counts of every child artifact, for the case detail view."""
        from spilltrace.db.models import (
            Attribution,
            CaseScene,
            DriftRun,
            EnvironmentalRun,
            EvidenceArtifact,
            Job,
            SpillDetection,
            Trajectory,
        )

        counts: dict[str, int] = {}
        for name, model, column in (
            ("scenes", CaseScene, CaseScene.case_id),
            ("detections", SpillDetection, SpillDetection.case_id),
            ("environmental_runs", EnvironmentalRun, EnvironmentalRun.case_id),
            ("drift_runs", DriftRun, DriftRun.case_id),
            ("trajectories", Trajectory, Trajectory.case_id),
            ("attributions", Attribution, Attribution.case_id),
            ("jobs", Job, Job.case_id),
            ("artifacts", EvidenceArtifact, EvidenceArtifact.case_id),
        ):
            stmt = select(func.count()).select_from(model).where(column == case_id)
            counts[name] = int((await self.session.execute(stmt)).scalar_one())
        return counts


__all__ = ["CaseRepository"]
