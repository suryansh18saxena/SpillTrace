"""Pure domain layer.

Nothing in this package may import from ``spilltrace.adapters``, ``spilltrace.db``,
``spilltrace.api`` or ``spilltrace.worker``.  Everything here is deterministic and
unit-testable without a database, a network or a framework.
"""
