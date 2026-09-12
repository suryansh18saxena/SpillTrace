"""Case-level provenance roll-up (CON-009, P23-011).

A case is created with the provenance its author *intends* (a real investigation is
``REAL``; a demonstration is ``SYNTHETIC``).  What the case actually contains is decided
later, by the pipeline: which scenes it found, what the detector was, where the AIS came
from.  ``cases.data_provenance`` must describe the evidence, not the intention, so it is
recomputed from every contributing artifact whenever a pipeline settles.

Rules (``combine_provenance``): REAL only if every input is REAL; SYNTHETIC only if
every input is SYNTHETIC; otherwise MIXED.  A case with **no** evidence yet keeps its
declared value — an empty case is not evidence of anything.

Run ``python -m spilltrace.db.provenance`` to backfill every existing case.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spilltrace.core.enums import DataProvenance
from spilltrace.core.provenance import combine_provenance
from spilltrace.db.models import (
    Attribution,
    Case,
    CaseScene,
    DriftRun,
    EnvironmentalRun,
    SatelliteScene,
    SpillDetection,
    Trajectory,
)
from spilltrace.logging import get_logger

log = get_logger(__name__)


async def contributing_provenance(session: AsyncSession, case_id: uuid.UUID) -> list[str]:
    """Distinct provenance labels of everything the pipeline has attached to the case."""
    values: set[str] = set()

    scenes = await session.execute(
        select(SatelliteScene.data_provenance)
        .join(CaseScene, CaseScene.scene_id == SatelliteScene.id)
        .where(CaseScene.case_id == case_id)
        .distinct()
    )
    values.update(v for v in scenes.scalars() if v)

    for model in (SpillDetection, DriftRun, EnvironmentalRun, Trajectory, Attribution):
        column = getattr(model, "data_provenance", None)
        if column is None:  # pragma: no cover - every listed model carries the column
            continue
        rows = await session.execute(select(column).where(model.case_id == case_id).distinct())
        values.update(v for v in rows.scalars() if v)
    return sorted(values)


async def rollup_case_provenance(session: AsyncSession, case: Case) -> DataProvenance:
    """Recompute and store the case's provenance from its evidence.

    Returns the value now held by the case.  The declared value survives only while the
    case holds no evidence at all.
    """
    values = await contributing_provenance(session, case.id)
    if not values:
        return DataProvenance(case.data_provenance)
    rolled = combine_provenance(*values)
    if rolled.value != case.data_provenance:
        log.info(
            "case_provenance_rolled_up",
            case_id=str(case.id),
            previous=case.data_provenance,
            rolled=rolled.value,
            inputs=values,
        )
        case.data_provenance = rolled.value
        await session.flush()
    return rolled


async def backfill(session: AsyncSession) -> dict[str, Any]:
    """Roll up every case; used once after the rule was introduced."""
    cases = list((await session.execute(select(Case))).scalars().all())
    changed: list[dict[str, str]] = []
    for case in cases:
        previous = case.data_provenance
        rolled = await rollup_case_provenance(session, case)
        if rolled.value != previous:
            changed.append({"case_ref": case.case_ref, "from": previous, "to": rolled.value})
    return {"cases": len(cases), "changed": changed}


async def _main() -> None:
    from spilltrace.db.session import session_scope

    async with session_scope() as session:
        result = await backfill(session)
    log.info("case_provenance_backfill", **result)
    print(result)


if __name__ == "__main__":
    asyncio.run(_main())
