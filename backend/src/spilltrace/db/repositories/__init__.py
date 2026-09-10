"""Repositories — every database read/write goes through here.

Two rules the rest of the codebase relies on:

1. **Ownership is enforced in the repository, not the router.**  A repository method
   that returns a case takes the requesting user and filters on it, so a forgotten check
   in a new endpoint cannot become an IDOR (NFR-009).
2. **No raw SQL string interpolation.**  Everything is a bound parameter (NFR-008).
"""

from spilltrace.db.repositories.base import Page, Repository
from spilltrace.db.repositories.cases import CaseRepository
from spilltrace.db.repositories.jobs import JobRepository
from spilltrace.db.repositories.users import UserRepository

__all__ = ["CaseRepository", "JobRepository", "Page", "Repository", "UserRepository"]
