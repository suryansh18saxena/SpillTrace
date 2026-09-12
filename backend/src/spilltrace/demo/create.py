"""``python -m spilltrace.demo.create`` — create the deterministic demo case from the CLI.

``make demo`` calls this.  It does exactly what ``POST /api/v1/demo/cases`` does, owned by
the first admin user, so a fresh stack can be demonstrated without opening the browser
first.  The case is SYNTHETIC and says so in its title, description and provenance.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from sqlalchemy import select

from spilltrace.config import get_settings
from spilltrace.core.disclaimers import SYNTHETIC_DATA_NOTICE
from spilltrace.core.enums import DataProvenance, UserRole
from spilltrace.core.geometry import bbox_polygon
from spilltrace.db.models import User
from spilltrace.db.repositories.cases import CaseRepository
from spilltrace.db.session import session_scope
from spilltrace.demo.scenarios import SCENARIOS, get_scenario
from spilltrace.worker.pipeline import create_pipeline, runnable_jobs
from spilltrace.worker.queue import JobQueue


async def create(
    scenario_key: str, seed: int, *, run_pipeline: bool, owner_email: str | None
) -> dict:
    scenario = get_scenario(scenario_key)
    settings = get_settings()
    async with session_scope() as session:
        query = select(User).where(User.is_active)
        if owner_email:
            query = query.where(User.email == owner_email)
        else:
            query = query.where(User.role == UserRole.ADMIN.value).order_by(User.created_at)
        owner = (await session.execute(query.limit(1))).scalar_one_or_none()
        if owner is None:
            raise SystemExit("No active admin user found; run 'make seed' first.")

        repo = CaseRepository(session)
        case = await repo.create(
            owner=owner,
            title=f"{scenario.title} (SYNTHETIC)",
            description=f"{scenario.description}\n\n{SYNTHETIC_DATA_NOTICE}",
            aoi=bbox_polygon(*scenario.aoi_bbox),
            start_time=scenario.case_start,
            end_time=scenario.case_end,
            provenance=DataProvenance.SYNTHETIC,
            scenario=scenario.key,
            seed=seed,
        )
        await session.flush()

        pipeline_id = None
        ready = []
        if run_pipeline:
            pipeline_id, _ = await create_pipeline(
                session, case=case, mode="DEMO", params={"scenario": scenario.key, "seed": seed}
            )
            ready = await runnable_jobs(session, pipeline_id)
        await session.commit()
        result = {
            "case_id": str(case.id),
            "case_ref": case.case_ref,
            "owner": owner.email,
            "scenario": scenario.key,
            "seed": seed,
            "pipeline_id": str(pipeline_id) if pipeline_id else None,
            "data_provenance": case.data_provenance,
        }

    if run_pipeline and ready:
        queue = JobQueue(settings)
        try:
            for job in ready:
                await queue.enqueue(job.id, priority=job.priority)
        finally:
            await queue.close()
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a SYNTHETIC demonstration case.")
    parser.add_argument("--scenario", default="kutch-01", choices=sorted(SCENARIOS))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--owner", default=None, help="Owner email (default: first admin).")
    parser.add_argument("--no-pipeline", action="store_true", help="Create only; do not run.")
    args = parser.parse_args(argv)
    result = asyncio.run(
        create(args.scenario, args.seed, run_pipeline=not args.no_pipeline, owner_email=args.owner)
    )
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
