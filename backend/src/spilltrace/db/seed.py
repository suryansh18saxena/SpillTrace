"""Seed the database with the accounts a fresh environment needs.

Idempotent: running it twice changes nothing.  Credentials come from the environment so
that no password is ever committed; the defaults below exist only for a local
development database and the script refuses to use them in production.
"""

from __future__ import annotations

import asyncio
import os
import secrets

from spilltrace.config import get_settings
from spilltrace.core.enums import UserRole
from spilltrace.db.repositories.users import UserRepository
from spilltrace.db.session import dispose_engine, session_scope
from spilltrace.logging import configure_logging, get_logger

log = get_logger(__name__)

# RFC 2606 reserved documentation domain: a valid address that can never route.
# ".local" was tried first and is correctly rejected as a special-use name.
DEFAULT_ADMIN_EMAIL = "admin@spilltrace.example.com"
DEFAULT_ANALYST_EMAIL = "analyst@spilltrace.example.com"


async def seed() -> dict[str, str]:
    settings = get_settings()
    created: dict[str, str] = {}

    admin_email = os.getenv("SPILLTRACE_ADMIN_EMAIL", DEFAULT_ADMIN_EMAIL)
    admin_password = os.getenv("SPILLTRACE_ADMIN_PASSWORD")
    analyst_email = os.getenv("SPILLTRACE_ANALYST_EMAIL", DEFAULT_ANALYST_EMAIL)
    analyst_password = os.getenv("SPILLTRACE_ANALYST_PASSWORD")

    if settings.is_production and not (admin_password and analyst_password):
        raise SystemExit(
            "Refusing to seed a production database with generated passwords. "
            "Set SPILLTRACE_ADMIN_PASSWORD and SPILLTRACE_ANALYST_PASSWORD."
        )

    async with session_scope() as session:
        users = UserRepository(session)

        for email, password, role, label in (
            (admin_email, admin_password, UserRole.ADMIN, "admin"),
            (analyst_email, analyst_password, UserRole.ANALYST, "analyst"),
        ):
            if await users.get_by_email(email) is not None:
                log.info("seed_user_exists", email=email, role=role.value)
                continue
            generated = password or f"spilltrace-{secrets.token_urlsafe(12)}"
            await users.create(
                email=email,
                password=generated,
                full_name=f"SPILLTRACE {label.title()}",
                role=role,
            )
            created[email] = generated if password is None else "(from environment)"
            log.info("seed_user_created", email=email, role=role.value)

    return created


async def _main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json_output=False)
    created = await seed()
    if created:
        print("\nSeeded accounts (store these now; generated passwords are not recoverable):")
        for email, password in created.items():
            print(f"  {email:32s} {password}")
    else:
        print("Nothing to seed: all accounts already exist.")
    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(_main())
